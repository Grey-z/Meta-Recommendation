async def search_products_amazon(
    query: str,
    ctx: any,
):
    results = await ctx.serpapi.search_amazon(query)
    items = []
    for result in results:
        extracted = {
            'title': result.get('title'),
            'brand': result.get('brand'),
            'link': result.get('link_clean'),
            'rating': result.get('rating'),
            'reviews': result.get('reviews'),
            'thumbnail': result.get('thumbnail'),
        }
        items.append(extracted)
    return items

    
