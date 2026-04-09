from string import Template

def format_book_genre_search_query(
    query: str,
    max_results: int=10,
):
    template = """
        query Query {
            search (
                query: "$query",
                query_type: "Book",
                per_page: $max_results,
                fields: "genres",
                weights: "1",
                sort: "users_read_count:desc",
                typos: "2",
                page: 1,
            ) {
                results
            }
        }
    """

    query_str = Template(template).substitute(
        query=query,
        max_results=max_results
    )

    return query_str

def parse_book_search_results(
    data
):
    try:
        hits = data['data']['search']['results']['hits']
    except:
        hits = []

    def parse_hit(hit):
        doc = hit['document']
        result = {}

        result['title'] = doc['title']
        result['genres'] = doc['genres']
        #result['tags'] = doc['tags']
        #result['moods'] = doc['moods']
        result['description'] = doc['description']
        result['url'] = Template('https://hardcover.app/books/$slug').substitute(
            slug=doc['slug']
        )

        return result

    
    results = list(map(parse_hit, hits))
    return results
    
