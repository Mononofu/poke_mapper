"""Pokemon Go API."""

import logging
import os
import time
import threading
import queue
import random
import signal
import sqlite3

from pgoapi import PGoApi
from pgoapi import utilities as util

import matplotlib.path
import s2sphere
import tqdm

import config
import pokedex

log = logging.getLogger(__name__)


class IndexDriver(object):
  def __init__(self):
    self.db_lock = threading.Lock()

    self.conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'pokemon.db'), check_same_thread=False)
    # Sqlite doesn't support uint64, so we have to store them as text..
    self.conn.execute('''CREATE TABLE IF NOT EXISTS Pokemon
                         (encounter_id text, pokemon_id integer, latitude real,
                          longitude real, spawn_point_id text, seen_timestamp integer,
                          visible_until integer, UNIQUE(encounter_id))''')
    self.conn.commit()

    self.pokedex = pokedex.Pokedex()
    self.num_pokemon = 0

  def run(self):
    self.running = True
    cell_queue = queue.Queue(1)
    threads = [ScanThread(c, cell_queue, self.on_pokemon) for c in config.CREDENTIALS]
    for t in threads:
      t.start()

    num_cells_scanned = 0

    while self.running:
      num_cells_scanned += self.generate_cells(cell_queue)
      logging.info('scanned %d cells', num_cells_scanned)

    logging.info('exiting, stopping threads...')

    for _ in threads:
      cell_queue.put(None)

    for t in threads:
      t.join()

  def generate_cells(self, cell_queue):
    old_num_pokemon = self.num_pokemon
    cells_seen = set()
    for name, polygon in config.LOCATIONS.iteritems():
      cells = flood_area(polygon).difference(cells_seen)
      logging.info('scanning %s', name)

      for c in tqdm.tqdm(cells):
        cell_queue.put(c)
        if not self.running:
          return 0

      cells_seen.update(cells)
      logging.info('done, found %d pokemon', self.num_pokemon - old_num_pokemon)

    return len(cells_seen)

  def stop(self):
    self.running = False

  def on_pokemon(self, pokemon):
    pokemon_id = pokemon['pokemon_data']['pokemon_id']

    with self.db_lock:
      self.conn.execute('INSERT OR IGNORE INTO Pokemon VALUES (?, ?, ? , ?, ?, ?, ?)',
                        (str(pokemon['encounter_id']), pokemon_id,
                         pokemon['latitude'], pokemon['longitude'],
                         str(pokemon['spawn_point_id']),
                         int(time.time()), pokemon['hides_at']))
      self.conn.commit()
      self.num_pokemon += 1


class ScanThread(threading.Thread):
  def __init__(self, credentials, cell_queue, report_callback):
    super(ScanThread, self).__init__()

    self.credentials = credentials
    self.scan_interval = 5  # Any faster than 1 scan / 5s and we get empty responses
    self.cell_queue = cell_queue
    self.api = PGoApi()
    self.batch_size = 10
    self.report_callback = report_callback
    self.daemon = True
    self.error_backoff = self.scan_interval

  def run(self):
    # Add a random initial delay to make threads don't operate in lock step.
    time.sleep(random.random() * self.scan_interval)

    while True:
      try:
        cell = self.cell_queue.get()
        if cell is None:
          return

        while not self.logged_in():
          time.sleep(self.scan_interval)
          self.login(cell)

        time.sleep(self.scan_interval)
        self.find_pokemon(cell)
        self.error_backoff = self.scan_interval
      except:
        logging.exception('account %s', self.credentials[1])
        time.sleep(self.error_backoff)
        self.error_backoff = min(self.error_backoff * 2, 300)

  def logged_in(self):
    if self.api._auth_provider and self.api._auth_provider._ticket_expire:
      min_batch_duration = self.batch_size * (self.scan_interval + 1)
      expired = self.api._auth_provider._ticket_expire / 1000 - time.time() < min_batch_duration
      if expired:
        logging.info('login ticket expired')
      return not expired
    else:
      return False

  def login(self, cell):
    lat, lng = lat_lng(cell)
    self.api.set_position(lat, lng, 0)  # provide player position on the earth
    return self.api.login(*self.credentials)

  def find_pokemon(self, cell):
    lat, lng = lat_lng(cell)
    self.api.set_position(lat, lng, 0)

    response_dict = self.api.get_map_objects(
        latitude=util.f2i(lat),
        longitude=util.f2i(lng),
        since_timestamp_ms=[0],
        cell_id=[cell.id()])

    if not response_dict['responses']:
      return
    responses = response_dict['responses']
    if 'status' not in responses['GET_MAP_OBJECTS'] or responses['GET_MAP_OBJECTS']['status'] != 1:
      return

    map_objects = responses['GET_MAP_OBJECTS']
    for map_cell in map_objects['map_cells']:
      if 'wild_pokemons' in map_cell:
        for pokemon in map_cell['wild_pokemons']:
          pokemon['hides_at'] = time.time() + pokemon[
              'time_till_hidden_ms'] / 1000
          self.report_callback(pokemon)


def main():
  logging.basicConfig(
      level=logging.INFO,
      format='%(asctime)s [%(module)10s] [%(levelname)5s] %(message)s')
  logging.getLogger('requests').setLevel(logging.WARNING)
  logging.getLogger('pgoapi').setLevel(logging.WARNING)
  logging.getLogger('rpc_api').setLevel(logging.WARNING)

  driver = IndexDriver()

  def handler(signum, frame):
    print '\n\ngot signal, stopping..'
    driver.stop()

  signal.signal(signal.SIGINT, handler)

  t = threading.Thread(target=driver.run)
  t.daemon = True
  t.start()

  signal.pause()

  t.join()


def lat_lng(cell):
  ll = cell.to_lat_lng()
  return ll.lat().degrees, ll.lng().degrees


def print_gmaps_dbug(cells, pokemons):
  url = 'http://maps.googleapis.com/maps/api/staticmap?size=800x800&markers='
  url += 'color:blue|'
  for cell in cells:
    ll = cell.to_lat_lng()
    url += '{},{}|'.format(ll.lat().degrees, ll.lng().degrees)
  for pokemon in pokemons:
    url += '&markers=label:' + pokemon['name'][0].upper()
    url += '|%s,%s' % (pokemon['latitude'], pokemon['longitude'])
  print url[:-1]


def flood_area(polygon):
  path = matplotlib.path.Path(polygon)

  # Calculated center.
  lat, lon = [sum(y) / len(y) for y in zip(*polygon)]
  starting_cell = s2sphere.CellId.from_lat_lng(s2sphere.LatLng.from_degrees(
      lat, lon)).parent(16)

  seen = set()
  cells = set()
  candidates = [starting_cell]

  # Add all cells that are strictly within the polygon.
  while candidates:
    cell = candidates.pop()

    if not path.contains_point(lat_lng(cell)):
      continue

    cells.add(cell)

    for neighbour in cell.get_edge_neighbors():
      if neighbour not in seen:
        seen.add(neighbour)
        candidates.append(neighbour)

  # Then add all cells on the border to make sure we cover the area.
  for cell in list(cells):
    for neighbour in cell.get_edge_neighbors():
      if neighbour not in cells:
        cells.add(neighbour)

  return cells


if __name__ == '__main__':
  main()
