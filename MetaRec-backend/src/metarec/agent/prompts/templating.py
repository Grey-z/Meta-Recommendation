from jinja2 import Template

def make_template(template_str):
    template = Template(template_str, trim_blocks=True, lstrip_blocks=True)
    return template
