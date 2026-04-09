from typing import Optional
#import json

async def search_music(query: str, ctx: any):
    """
    Lucene query. 
    see: https://musicbrainz.org/doc/MusicBrainz_API/Search#Recording
    """

    results = await ctx.musicbrainz.search_recordings(query)
    items = []
    for result in results:
        #temp = result.get('releases')
        #print(json.dumps(temp, indent=2))

        artists = map(lambda x: x.get('name'), result.get('artist-credit'))
        artists = list(artists)
        
        tags = map(lambda x: x.get('name'), result.get('tags'))
        tags = list(tags)

        link = None
        mbid = result.get('id')
        if mbid is not None:
            link = f'musicbrainz.org/recording/{mbid}'
        
        # 1. get a release
        # 2. get the release cover art
        # TODO: pick a better release instead of the first in the list??
        releases = result.get('releases', [])
        if len(releases) == 0:
            release = {}
        else:
            release = releases[0]
        
        try:
            cover_art_url = await ctx.coverartarchive.get_cover_art(mbid=release.get('id'))
        except:
            cover_art_url = None

        extracted = {
            'title': result.get('title'),
            'date': result.get('first-release-date'),
            'link': link,
            'artists': artists,
            'tags': tags,
            'cover_art_url': cover_art_url,
        }
        items.append(extracted)
    
    return items

async def search_movies_by_genres(
    with_genres: Optional[str],
    without_genres: Optional[str],
    ctx: any,
):
    results = await ctx.tmdb.search_movie_by_filter(
        with_genres=with_genres, 
        without_genres=without_genres,
    )

    config = await ctx.tmdb.get_configuration()
    genres_list = await ctx.tmdb.list_movie_genres()
    language_list = await ctx.tmdb.get_languages()

    img_base_url = config.get('images').get('secure_base_url')
    size = 'original'

    items = []
    for result in results:
        poster_path = result.get('poster_path')
        poster_url = None
        if poster_path is not None:
            poster_url = f'{img_base_url}{size}{poster_path}'
        
        genre_ids = result.get('genre_ids', [])
        genres = ctx.tmdb.map_genre_ids_to_names(genre_ids, genres_list)
        
        original_language = result.get('original_language')
        original_language = ctx.tmdb.map_language_code_to_name(original_language, language_list)

        extracted = {
            'title': result.get('title'),
            'release_date': result.get('release_date'),
            'overview': result.get('overview'),

            'vote_count': result.get('vote_count'),
            'popularity': result.get('popularity'),
            'vote_average': result.get('vote_average'),

            # post processed values
            'original_language': original_language,
            'poster_url': poster_url,
            'genres': genres,
        }
        items.append(extracted)
    return items
    

async def search_movies_by_title(query: str, ctx: any):
    results = await ctx.tmdb.search_movie_by_title(query)

    config = await ctx.tmdb.get_configuration()
    genres_list = await ctx.tmdb.list_movie_genres()
    language_list = await ctx.tmdb.get_languages()
    img_base_url = config.get('images').get('secure_base_url')
    size = 'original'

    items = []
    for result in results:
        poster_path = result.get('poster_path')
        poster_url = None
        if poster_path is not None:
            poster_url = f'{img_base_url}{size}{poster_path}'
        
        genre_ids = result.get('genre_ids', [])
        genres = ctx.tmdb.map_genre_ids_to_names(genre_ids, genres_list)
        
        original_language = result.get('original_language')
        original_language = ctx.tmdb.map_language_code_to_name(original_language, language_list)

        extracted = {
            'title': result.get('title'),
            'release_date': result.get('release_date'),
            'overview': result.get('overview'),

            'vote_count': result.get('vote_count'),
            'popularity': result.get('popularity'),
            'vote_average': result.get('vote_average'),

            # post processed values
            'original_language': original_language,
            'poster_url': poster_url,
            'genres': genres,
        }
        items.append(extracted)
    return items

async def search_tv_by_genres(
    with_genres: Optional[str],
    without_genres: Optional[str],
    ctx: any,
):
    results = await ctx.tmdb.search_tv_by_filter(
        with_genres=with_genres, 
        without_genres=without_genres,
    )

    config = await ctx.tmdb.get_configuration()
    genres_list = await ctx.tmdb.list_tv_genres()
    language_list = await ctx.tmdb.get_languages()
    
    img_base_url = config.get('images').get('secure_base_url')
    size = 'original'
    items = []
    for result in results:
        poster_path = result.get('poster_path')
        poster_url = None
        if poster_path is not None:
            poster_url = f'{img_base_url}{size}{poster_path}'

        genre_ids = result.get('genre_ids', [])
        genres = ctx.tmdb.map_genre_ids_to_names(genre_ids, genres_list)

        original_language = result.get('original_language')
        original_language = ctx.tmdb.map_language_code_to_name(original_language, language_list)

        extracted = {
            'name': result.get('name'),
            'first_air_date': result.get('first_air_date'),
            'overview': result.get('overview'),

            'vote_count': result.get('vote_count'),
            'popularity': result.get('popularity'),
            'vote_average': result.get('vote_average'),

            # post processed values
            'original_language': original_language,
            'poster_url': poster_url,
            'genres': genres,
        }
        items.append(extracted)
    return items

async def search_tv_by_title(query: str, ctx: any):
    results = await ctx.tmdb.search_tv_by_title(query)
    config = await ctx.tmdb.get_configuration()
    genres_list = await ctx.tmdb.list_tv_genres()
    language_list = await ctx.tmdb.get_languages()
    
    img_base_url = config.get('images').get('secure_base_url')
    size = 'original'
    items = []
    for result in results:
        poster_path = result.get('poster_path')
        poster_url = None
        if poster_path is not None:
            poster_url = f'{img_base_url}{size}{poster_path}'

        genre_ids = result.get('genre_ids', [])
        genres = ctx.tmdb.map_genre_ids_to_names(genre_ids, genres_list)

        original_language = result.get('original_language')
        original_language = ctx.tmdb.map_language_code_to_name(original_language, language_list)

        extracted = {
            'name': result.get('name'),
            'first_air_date': result.get('first_air_date'),
            'overview': result.get('overview'),

            'vote_count': result.get('vote_count'),
            'popularity': result.get('popularity'),
            'vote_average': result.get('vote_average'),

            # post processed values
            'original_language': original_language,
            'poster_url': poster_url,
            'genres': genres,
        }
        items.append(extracted)
    return items

async def search_books(query: str, ctx: any):
    """
    graphql query
    """
    results = await ctx.hardcover.search_books_by_genre(query)
    items = []
    for result in results:
        print(result)

        # extract author data
        authors = []
        contributions = result.get('document').get('contributions')
        for entry in contributions:
            if 'author' in entry:
                author = entry.get('author').get('name')
                authors.append(author)
        
        #extract link data
        link = None
        slug = result.get('document').get('slug', None)
        if slug is not None:
            link = f'https://hardcover.app/books/{slug}'
        
        extracted = {
            'title': result.get('document').get('title'),
            'release_date': result.get('document').get('release_date'),
            'ratings_count': result.get('document').get('ratings_count'),
            'reviews_count': result.get('document').get('reviews_count'),
            'description': result.get('document').get('description'),
            'image': result.get('document').get('image').get('url'),
            'genres': result.get('document').get('genres'),
            'moods': result.get('document').get('moods'),
            'tags': result.get('document').get('tags'),
            'authors': authors,
            'hardcover_link': link,
        }

        items.append(extracted)
    return items
