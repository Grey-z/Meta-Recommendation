# observations and reasonings
- existing code is large and hard to read
- service.py, llm_service.py very large 1000+ lines
- service.py is a very bloated file, appears hard to maintain and make changes
- using pyan3 to do a vizualization of function calls
    - very complex, without even adding other search/recommendation domains beyond restaurants

# goals?
- make code a more easily maintainable and navigatable
- refactor to use langgraph Graph API to make defining workflows easier
    - I want to separate this imperative logic into langgraph nodes and edges
        - each noded should internally handle whether it uses LLM or regex, and fallback to regex if LLM call fails for some reason
        - transitions between nodes should be defined using langgraph edge function calls
- seperation of concerns, grouping related functions together
- fastmcp, MCP
    - for things to be used pass to LLM during completion calls
    - tool calling via MCP client, not via the actual functions
    - prompts


# how messages are added in UI
## by user
- `press button yes` - adds a message saying "Yes"
- `press button no` - adds a message saying "No"
- `send message` - adds the send message
- `press button yes on preferences` - adds a message summarizing preferences (formatted on the frontend side)

## by the UI in based on the response created by sending the above messages  to `recommend()`
- in response to onSend
    - if has `llm_reply` - sends another request to recommendStream which generates a message based on the conversation history
    - if has `confirmation_request` 
        - if guidance case (confirmation_no intent)
            - shows preference form with confirm button
        - else:
            - shows YES / NO
        - saves the message part only to backend
    - if has `thinking_steps`
        - passes responsibility to handleTaskCreated
    - otherwise (assumes has `restaurants`) creates a message showing results
        - saves a text only version to backend
        - adds a frontend only UI element to message list
    - any error adds an error message instead

- in handlePreferenceConfirm: 
    - creates a text summary of the preferences (on the frontend side)
    - sends that text based summary to the backend as a message
    - if has `llm_reply`
        - adds directly as a assistant message
    - if has `confirmation_request`
        - similar to onSend
    - if has `thinking_steps` - same as onSend
    - if has `restaurants` - results

- reloading on chats results in UI chat elements disappearing and becoming non-functional
- yes / no floating element attaches to the last assistant message
- confirm perference buttis is within its own message

# documentation of current and updated directory structure
- pyproject.toml
    - to turn the project into an installable python package
    - python -m pip install -e .
    - python -m build --wheel
- Metarec-ui
    - frontend is too coupled with backend logic
    - api should simply be chat with handlers for various outputs, whether response or SSE
    - task status polling
        - status is polled in two hooks
            - 1 hook per task, and 1 for the "currentTaskId"
            - polling is done while the element is rendered, and only stops after being unmounted
            - status of "complete" tasks are also polled
    - ui handling adding of messages (e.g. task views) means that tasks could disappear
- Metarec-backend
    - analysis.py: for generating call graph image using pyan3, graphviz
    - viz.png: visualization of workflow/pipeline
    - .env: environment variables
    - requirements.txt
        - TODO, deprecate in favour of pyroject.toml

    - client.py: to create openai clients
    - internal/: for unit testing???? (moved)
    - agent/ (moved)
        - planning to refactor these to use langgraph instead
        - agent_executor.py
        - agent_planner.py
        - agent_summary.py
        - agent_mcp/
            - agent_google_maps.py
            - agent_xiaohongshu.py
            - agent_yelp.py
    - src/
        - metarec/
            - legacy/ ( v1 api)
                - llm_service.py: various llm completion functions
                - service.py: defines MetaRecService and its various capabilities
                - main.py
                    - a lot of the conversation logic is handled by the UI sides Chat.tsx or MetaRecPage.tsx, but those 
                    logic should on the backend
                    - calls to either llm_service or service
                 -conversation_storage.py
                    - highly coupled with conversation schema
                    - allow langgraph to handle conversation state
                - user_profile_storage.py
            - llm_client.py ( renamed, moved client.py )
            - service/ (v2 api)
                - __main__.py: starts fastAPI app
                - router.py: defines the API endpoints, creating a fastapi.APIRouter instance
                - models.py: data models
                - conversation.py: conversation logic, interacting with langgraph graph
                - session.py: session logic (userId -> conversationList, etc.)
            - internal/: ( moved  )
                - router.py
                - registry.py
            - preferences/
                - registry.py:
                    - defines PreferenceRegistry
                    - defines PreferenceSpec
                - domains/
                    - <domain>.py: define PreferenceSpec for a specific domain
                    - restaurant.py
                    - books.py
            - agent/
                - state.py:
                    - defines AgentState data class for use with langgraph
                - context.py:
                    - defines a ClientContext instance which contains provider.base.Client instances for the various APIs
                    - TODO: should probably be moved under provider/
                - graph.py: declaratively define pipeline,workflow
                - mcp_server.py: create a FastMCP server instance
                - nodes/: for defining capabilities of the pipeline steps
                    - <category.py>: group related nodes
                    - recommendation.py: recommendation related functions
                        - TODO: at the moment contains all nodes for the recommendation subgraph, maybe consider
                          probably split these
                    - analysis.py: classifying user inputs?
                    - routing.py: utility function for picking route key from state
                    - feedback.py: human in the loop
                    - tools.py: WIP, testing tool calling by llm
                    - utils.py: contains only a no-op placeholder function
                - providers/
                    - base.py: base client class
                    - <provider_name>/
                        - client.py: extendsd base client class to interface with the providers API
                    - serpapi/: serpapi API for google map, yelp, amazon search
                    - discogs/: music search
                    - hardcover/: book search
                    - musicbrainz/: music search
                    - coverartarchive/: music album(?) cover art search (coupled with musicbrainz)
                    - tmdb/: movie/tv search
                    - tikhub/: xiaohongshu search
                - llm/
                    - TODO: for llm related functions for refactoring llm_service.py?
                - tools/
                    - <domain>.py: use various API clients under providers to achive something
                    - tool function signature should be name(...args, ctx)
                    - restaurants.py: uses API clients to do something search for restaurants
                    - entertainment.py: uses API clients to do something search for entertainment (book, movie, tv, music)
                    - shopping.py: uses API clients to do something search for shopping (amazon search)
                - prompts/
                    - TBD: write template strings in separate files? or keep as variables?
                    - __init__.py: hoist functions to package level
                    - templating.py: 
                        - make_template() wraps jinja2.Template() with lstrip_blocks=True and trim_blocks=True
                    - <category>.py: group various prompt generation templates under certain categories
                    - search.py: missing_preferences, 
                    - routing.py: detect_intent

# misc 
- state machine engine / `langgraph`
    - using Graph API for defining workflows / pipelines in declarative manner instead of imperatively
        - auto generation of flowchart
        - easier to understand business logic
        - easier to maintain and make changes in the future
    - handles conversation tracking via `config.configurable.thread_id`
    - node function signatures -> function(state, config, runtime)
        - state: should be serializable, contains things that may change during the course of the workflow
        - config: should be serializable, contains things like setting??
        - runtime: other things injected into state engine that we dont want to make traces e.g. Client objects?? idk

- MCP / `fastmcp`
    - why??
    
- alternatives state machine engines?
    - some discussions i see people are not too fond of langgraph/langchain etc.

