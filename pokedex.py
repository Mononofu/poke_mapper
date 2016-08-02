import json
import os


class Pokedex(object):
  """Metadata about Pokemon."""

  def __init__(self):
    """Load data."""
    self._pokemon = {}
    with open(os.path.join(os.path.dirname(__file__), 'pokemon.json')) as f:
      for pokemon in json.load(f):
        self._pokemon[int(pokemon['Number'])] = pokemon

  def name_by_id(self, id):
    """Get Pokemon name from their id."""
    return self._pokemon[id]['Name']
