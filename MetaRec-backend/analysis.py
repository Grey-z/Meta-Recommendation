import pyan
import graphviz

filenames = [
    'service.py', 
    'llm_service.py', 
]

#filenames = ['../service.py', '../main.py']
#filenames = ['mcp_server.py', 'tools/*.py', 'context.py', 'providers/base.py', 'providers/**/client.py']
#filenames = ['../preferences/*.py', '../preferences/**/*.py']
src = pyan.create_callgraph(
        filenames=filenames,
        format="dot",
        colored=True,
        annotated=True,
        nested_groups=True,
        depth=None,
        direction="both",
        concentrate=True,
        draw_defines=False, draw_uses=True,
        #draw_uses=False, draw_defines=True,
        layout="dot",
        ranksep="2.0",
    )

final = []
for line in src.split('\n'):
    if "__init__" in line:
        continue

    final.append(line)

src = '\n'.join(final)

with open('Source.gv', 'w') as f:
    f.write(src)

src = graphviz.Source(src)
src.view()


