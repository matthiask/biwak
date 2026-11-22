"""The drawn marks (specs/people.md, "Stage 2: drawn marks"): one of the
drawings in ``biwak/static/biwak/marks/`` per person, shown in white on
the palette color of their ID wherever they have no photo. Drawn through
a CSS mask, one class per mark (``frontend/styles/marks.css``)."""

from django.db.models import Count, Q
from django.utils.translation import pgettext_lazy


# The order of the choice in the settings, and of giving them: of those
# fewest people of the organization have, the first here. The alpine
# ones first, then the generic ones.
MARKS = {
    "tent": pgettext_lazy("mark", "Tent"),
    "mountain": pgettext_lazy("mark", "Mountain"),
    "horn": pgettext_lazy("mark", "Alphorn"),
    "lake": pgettext_lazy("mark", "Lake"),
    "fir": pgettext_lazy("mark", "Fir"),
    "ibex": pgettext_lazy("mark", "Ibex"),
    "marmot": pgettext_lazy("mark", "Marmot"),
    "edelweiss": pgettext_lazy("mark", "Edelweiss"),
    "gentian": pgettext_lazy("mark", "Gentian"),
    "ice-axe": pgettext_lazy("mark", "Ice axe"),
    "campfire": pgettext_lazy("mark", "Campfire"),
    "lantern": pgettext_lazy("mark", "Lantern"),
    "backpack": pgettext_lazy("mark", "Backpack"),
    "boot": pgettext_lazy("mark", "Boot"),
    "cable-car": pgettext_lazy("mark", "Cable car"),
    "hut": pgettext_lazy("mark", "Hut"),
    "sunrise": pgettext_lazy("mark", "Sunrise"),
    "moon": pgettext_lazy("mark", "Moon"),
    "snowflake": pgettext_lazy("mark", "Snowflake"),
    "cloud": pgettext_lazy("mark", "Cloud"),
    "eagle": pgettext_lazy("mark", "Eagle"),
    "cowbell": pgettext_lazy("mark", "Cowbell"),
    "cheese": pgettext_lazy("mark", "Cheese"),
    "fox": pgettext_lazy("mark", "Fox"),
    "owl": pgettext_lazy("mark", "Owl"),
    "cat": pgettext_lazy("mark", "Cat"),
    "fish": pgettext_lazy("mark", "Fish"),
    "leaf": pgettext_lazy("mark", "Leaf"),
    "mushroom": pgettext_lazy("mark", "Mushroom"),
    "cup": pgettext_lazy("mark", "Cup"),
    "paper-plane": pgettext_lazy("mark", "Paper plane"),
    "anchor": pgettext_lazy("mark", "Anchor"),
    "heart": pgettext_lazy("mark", "Heart"),
    "rocket": pgettext_lazy("mark", "Rocket"),
    "star": pgettext_lazy("mark", "Star"),
}


def fewest_used(used):
    """Of the marks, the one ``used`` (mark -> people) has least often;
    ties: the first in ``MARKS``"""
    return min(MARKS, key=lambda mark: used.get(mark, 0))


def mark_for(organization_id):
    """The mark for somebody new in the organization (``None``: without
    one): the one fewest of its people who haven't left have, so a team
    of up to 35 has no repeats. Those waiting to be activated count too:
    an import's people are inactive until then, and would all get the
    same mark otherwise."""
    from biwak.accounts.models import User

    people = User.objects.filter(
        Q(is_active=True) | Q(left_at__isnull=True), organization_id=organization_id
    )
    used = dict(
        people
        .exclude(mark="")
        # Without the people's ordering, which would split the groups
        .order_by()
        .values("mark")
        .annotate(n=Count("pk"))
        .values_list("mark", "n")
    )
    return fewest_used(used)
