from django import template

from biwak.checkins import operations as ops


register = template.Library()


@register.inclusion_tag("checkins/_due.html", takes_context=True)
def checkins_due(context, project):
    """The person's questions waiting for an answer, on the project page"""
    return {"due": ops.due(context["request"].user, project=project)}
