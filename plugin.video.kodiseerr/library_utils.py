import json
import xbmc
import xbmcgui
import xbmcaddon

_MEDIA_ADDONS = [
    ('plugin.video.jellycon',        'Jellycon'),
    ('plugin.video.emby',            'Emby for Kodi'),
    ('plugin.video.plexkodiconnect', 'Plex for Kodi'),
]
_addon_check_cache = {}


def _addon_installed(addon_id):
    if addon_id not in _addon_check_cache:
        try:
            xbmcaddon.Addon(addon_id)
            _addon_check_cache[addon_id] = True
        except Exception:
            _addon_check_cache[addon_id] = False
    return _addon_check_cache[addon_id]


def get_installed_media_addons():
    return [(aid, name) for aid, name in _MEDIA_ADDONS if _addon_installed(aid)]


def _find_movie(tmdb_id, imdb_id=''):
    resp = json.loads(xbmc.executeJSONRPC(json.dumps({
        'jsonrpc': '2.0', 'method': 'VideoLibrary.GetMovies',
        'params': {'properties': ['uniqueid']}, 'id': 1,
    })))
    for m in resp.get('result', {}).get('movies', []):
        u = m.get('uniqueid', {})
        if (str(u.get('tmdb', '')) == str(tmdb_id)
                or (imdb_id and str(u.get('imdb', '')) == str(imdb_id))):
            return m.get('movieid')
    return None


def _find_tvshow(tmdb_id, imdb_id='', tvdb_id=''):
    resp = json.loads(xbmc.executeJSONRPC(json.dumps({
        'jsonrpc': '2.0', 'method': 'VideoLibrary.GetTVShows',
        'params': {'properties': ['uniqueid']}, 'id': 1,
    })))
    for s in resp.get('result', {}).get('tvshows', []):
        u = s.get('uniqueid', {})
        if (str(u.get('tmdb', '')) == str(tmdb_id)
                or (tvdb_id and str(u.get('tvdb', '')) == str(tvdb_id))
                or (imdb_id and str(u.get('imdb', '')) == str(imdb_id))):
            return s.get('tvshowid')
    return None


def find_next_episode(tmdb_id, tvdb_id='', imdb_id=''):
    show_id = _find_tvshow(tmdb_id, imdb_id, tvdb_id)
    if not show_id:
        return None
    resp = json.loads(xbmc.executeJSONRPC(json.dumps({
        'jsonrpc': '2.0', 'method': 'VideoLibrary.GetEpisodes',
        'params': {
            'tvshowid': show_id,
            'properties': ['season', 'episode', 'file', 'playcount'],
            'filter': {'field': 'playcount', 'operator': 'is', 'value': '0'},
        }, 'id': 1,
    })))
    episodes = [e for e in resp.get('result', {}).get('episodes', []) if e.get('season', 0) > 0]
    if not episodes:
        return None
    episodes.sort(key=lambda e: (e.get('season', 0), e.get('episode', 0)))
    ep = episodes[0]
    return ep.get('season'), ep.get('episode'), ep.get('file')


def _external_ids(media_type, media_id):
    import api_client
    import cache
    cache_key = f"details_{media_type}_{media_id}"
    data = cache.get_cached(cache_key)
    if not data:
        data = api_client.client.api_request(f"/{media_type}/{media_id}")
        if data:
            cache.set_cached(cache_key, data)
    ext = (data or {}).get('externalIds', {})
    return str(media_id), str(ext.get('imdbId') or ''), str(ext.get('tvdbId') or '')


_MOVIE_PROPS = ['title', 'originaltitle', 'sorttitle', 'plot', 'plotoutline', 'tagline', 'year',
                'rating', 'votes', 'ratings', 'userrating', 'genre', 'director', 'writer', 'studio',
                'country', 'mpaa', 'runtime', 'premiered', 'playcount', 'lastplayed', 'dateadded',
                'file', 'art', 'trailer', 'imdbnumber', 'uniqueid', 'set', 'setid', 'tag', 'top250',
                'resume', 'cast']


def open_local(media_type, media_id):
    """danaimone fork: a title Seerr marks available opens its Kodi library entry
    instead of a "request anyway?" prompt. Movies get the skin's info dialog
    (poster, plot, ratings, Play); shows open their season list.
    Returns False when the title is not in the Kodi library."""
    tmdb_id, imdb_id, tvdb_id = _external_ids(media_type, media_id)
    if media_type != 'movie':
        db_id = _find_tvshow(tmdb_id, imdb_id, tvdb_id)
        if not db_id:
            return False
        xbmc.executebuiltin(f'ActivateWindow(Videos,videodb://tvshows/titles/{db_id}/,return)')
        return True
    db_id = _find_movie(tmdb_id, imdb_id)
    if not db_id:
        return False
    resp = json.loads(xbmc.executeJSONRPC(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'VideoLibrary.GetMovieDetails',
        'params': {'movieid': db_id, 'properties': _MOVIE_PROPS},
    })))
    m = (resp.get('result') or {}).get('moviedetails') or {}
    li = xbmcgui.ListItem(m.get('title') or m.get('label') or '')
    path = m.get('file') or f'videodb://movies/titles/{db_id}'
    li.setPath(path)
    li.setProperty('IsPlayable', 'true')
    tag = li.getVideoInfoTag()
    tag.setDbId(int(db_id))
    tag.setMediaType('movie')
    tag.setFilenameAndPath(path)
    simple = {
        'title': tag.setTitle, 'originaltitle': tag.setOriginalTitle, 'sorttitle': tag.setSortTitle,
        'plot': tag.setPlot, 'plotoutline': tag.setPlotOutline, 'tagline': tag.setTagLine,
        'mpaa': tag.setMpaa, 'premiered': tag.setPremiered, 'lastplayed': tag.setLastPlayed,
        'dateadded': tag.setDateAdded, 'trailer': tag.setTrailer, 'imdbnumber': tag.setIMDBNumber,
        'set': tag.setSet,
    }
    for key, setter in simple.items():
        v = m.get(key)
        if v:
            try:
                setter(v)
            except Exception:
                pass
    lists = {'genre': tag.setGenres, 'director': tag.setDirectors, 'writer': tag.setWriters,
             'studio': tag.setStudios, 'country': tag.setCountries, 'tag': tag.setTags}
    for key, setter in lists.items():
        v = m.get(key)
        if v:
            try:
                setter(list(v))
            except Exception:
                pass
    ints = {'year': tag.setYear, 'runtime': tag.setDuration, 'playcount': tag.setPlaycount,
            'userrating': tag.setUserRating, 'top250': tag.setTop250, 'setid': tag.setSetId}
    for key, setter in ints.items():
        v = m.get(key)
        if v:
            try:
                setter(int(v))
            except Exception:
                pass
    try:
        ratings = m.get('ratings') or {}
        for src, r in ratings.items():
            tag.setRating(float(r.get('rating') or 0), int(r.get('votes') or 0), src, bool(r.get('default')))
        if not ratings and m.get('rating'):
            tag.setRating(float(m['rating']), int(m.get('votes') or 0), 'default', True)
    except Exception:
        pass
    try:
        if m.get('uniqueid'):
            tag.setUniqueIDs(dict(m['uniqueid']), 'tmdb' if 'tmdb' in m['uniqueid'] else '')
    except Exception:
        pass
    try:
        res = m.get('resume') or {}
        if res.get('position'):
            tag.setResumePoint(float(res['position']), float(res.get('total') or 0))
    except Exception:
        pass
    try:
        tag.setCast([xbmc.Actor(c.get('name', ''), c.get('role', ''), int(c.get('order', i)), c.get('thumbnail', ''))
                     for i, c in enumerate(m.get('cast') or []) if c.get('name')])
    except Exception:
        pass
    if m.get('art'):
        li.setArt(m['art'])
    xbmcgui.Dialog().info(li)
    return True


def jump_to_library(media_type, media_id):
    tmdb_id, imdb_id, tvdb_id = _external_ids(media_type, media_id)
    if media_type == 'movie':
        db_id = _find_movie(tmdb_id, imdb_id)
        if db_id:
            xbmc.executebuiltin(
                f'ActivateWindow(VideoLibrary,videodb://movies/titles/{db_id}/,return)'
            )
        else:
            xbmcgui.Dialog().notification(
                'KodiSeerr', 'Not found in local library',
                xbmcgui.NOTIFICATION_WARNING, 3000
            )
    else:
        db_id = _find_tvshow(tmdb_id, imdb_id, tvdb_id)
        if db_id:
            xbmc.executebuiltin(
                f'ActivateWindow(VideoLibrary,videodb://tvshows/titles/{db_id}/,return)'
            )
        else:
            xbmcgui.Dialog().notification(
                'KodiSeerr', 'Not found in local library',
                xbmcgui.NOTIFICATION_WARNING, 3000
            )


def get_library_context_items(media_type, media_id, status):
    from utils import build_url
    if status not in (4, 5):
        return []
    items = [(
        'View in Local Library',
        f'RunPlugin({build_url({"mode": "jump_to_library", "type": media_type, "id": media_id})})'
    )]
    if media_type == 'tv':
        items.append((
            'Play Next Episode',
            f'RunPlugin({build_url({"mode": "play_next_episode", "type": media_type, "id": media_id})})'
        ))
    for addon_id, addon_name in get_installed_media_addons():
        items.append((
            f'Browse in {addon_name}',
            f'ActivateWindow(Videos,plugin://{addon_id}/,return)'
        ))
    return items
