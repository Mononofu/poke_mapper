import collections
import os
import sqlite3

import flask

import pokedex

app = flask.Flask(__name__)
conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'pokemon.db'), check_same_thread=False)
pokedex = pokedex.Pokedex()


def list_pokemon():
  for row in conn.execute('SELECT latitude, longitude, pokemon_id FROM Pokemon'):
    yield {'lat': row[0], 'lng': row[1], 'id': row[2]}


@app.route("/")
def index():
  def yield_ids():
    for p in list_pokemon():
      yield p['id']
  return flask.render_template('index.html',
                               pokemon_counts=collections.Counter(yield_ids()),
                               pokedex=pokedex)


@app.route('/api/pokemon/')
def api_pokemon():
  return flask.jsonify(*list_pokemon())

if __name__ == "__main__":
    app.run(debug=True)
