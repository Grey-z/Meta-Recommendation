async def search_restaurants_google(query: str, ctx: any):
    results = await ctx.serpapi.search_google(query)
    items = []
    for item in results:
        extracted = {
            'title': item.get('title'),
            'rating': item.get('rating'),
            'reviews': item.get('reviews'),
            'reviews_link': item.get('reviews_link'),
            'photos_link': item.get('photos_link'),
            'price': item.get('price'),
            'type': item.get('type'),
            'address': item.get('address'),
            'phone': item.get('phone'),
            'hours': item.get('hours'),
            'service_options': item.get('service_options'),
            'gps_coordinates': item.get('gps_coordinates', {}),
            "user_reviews": item.get('user_reviews'),
            "operating_hours": item.get('operating_hours'),
            "open_state": item.get('open_state'),
            "extensions": item.get('extensions')
        }
        items.append(extracted)
    return items

async def search_restaurants_xiaohongshu(query: str, ctx: any):
    results = await ctx.tikhub.search_xiaohongshu(keyword=query)
    items = []
    for result in results:
        note_data = result.get('note')
        
        publish_time = None
        corner_tag_info = note_data.get('corner_tag_info', [])
        for tag in corner_tag_info:
            if tag.get('type') == 'publish_time':
                publish_time = tag.get('text')
                break

        item = {
            'id': note_data.get('id'),
            'title': note_data.get('title'),
            'desc': note_data.get('desc'),
            'collected_count': note_data.get('collected_count'),
            'comments_count': note_data.get('comments_count'),
            'liked_count': note_data.get('liked_count'),
            'shared_count': note_data.get('shared_count'),
            'publish_time': publish_time
        }
        items.append(item)
    return items

async def search_restaurants_yelp(query: str, location: str, ctx: any):
    results = await ctx.serpapi.search_yelp(query, location)
    items = []
    for item in results:
        extracted = {
            'position': item.get('position'), # yelp ranking within search results
            'place_ids': item.get('place_ids', []),
            'title': item.get('title'),
            'link': item.get('link'),
            'reviews_link': item.get('reviews_link'),
            'thumbnail': item.get('thumbnail'),
            'categories': item.get('categories', []),
            'price': item.get('price'), # price range $-$$$
            'rating': item.get('rating'), # average rating
            'reviews': item.get('reviews'), # number of reviews, not review content
            'highlights': item.get('highlights', []), # yelp highlighted keywords?
            'phone': item.get('phone'), # appears in some results, not all
            'neighborhoods': item.get('neighborhoods'), # appears in some results, not all
            'snippet': item.get('snippet'), # seems to be a featured review OR summary of reviews?
        }
        items.append(extracted)

    return items
