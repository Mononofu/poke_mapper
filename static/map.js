var map, heatmap;
var pokemons = [];

document.getElementById('map').style.height = (window.innerHeight - 100) + 'px';

function initMap() {
  map = new google.maps.Map(document.getElementById('map'), {
    zoom: 12,
    center: {lat: 51.535662, lng: -0.132125},
  });

  var req = new XMLHttpRequest();
  req.onreadystatechange = function() {
    if (req.readyState == 4 && req.status == 200) {
      pokemons = JSON.parse(req.responseText);
      showHeatmap();
    }
  };
  req.open('GET', '/api/pokemon/', true);  // true for asynchronous
  req.send(null);
}

function showHeatmap() {
  if (!map) return;

  if (heatmap) {
    // Remove previous heatmaps.
    heatmap.setMap(null);
  }

  var points = [];
  for (var pokemon of pokemons) {
    if (isActive([pokemon['id']])) {
      points.push(new google.maps.LatLng(pokemon.lat, pokemon.lng));
    }
  }

  heatmap =
      new google.maps.visualization.HeatmapLayer({data: points, map: map});
}

var inactivePokemon = {};

function isActive(pokeId) {
  return !(pokeId in inactivePokemon) || inactivePokemon[pokeId] === true;
}

function setActive(pokeId, active) {
  inactivePokemon[pokeId] = active;

  var li = document.getElementById('poke_' + pokeId);
  if (li) {
    if (active) {
      li.classList.remove('inactive');
    } else {
      li.classList.add('inactive');
    }
  }
}

function toggleActive(pokeId) {
  setActive(pokeId, !isActive(pokeId));
  showHeatmap();
}

for (var commonPokemon of [16, 19, 41, 96]) {
  setActive(commonPokemon, false);
}

function enableAll() {
  for (var i = 1; i <= 151; i++) {
    setActive(i, true);
  }
  showHeatmap();
}

function disableAll() {
  for (var i = 1; i <= 151; i++) {
    setActive(i, false);
  }
  showHeatmap();
}
