"""How a person's short name is shown to a viewer (specs/ui-round-2.md,
part F): "Moritz", but "Moritz F." when somebody else the viewer may know
has the same short name, and the full name when that is still the same.
The rule lives here, nowhere else; everything that prints a short name
(templates, mentions, the ``@`` list, mails) asks ``display_name()``."""

from collections import defaultdict


def short_label(person, same):
    """The name of ``person`` among ``same``, the people with their short
    name: the first letter of the last name appended, else the full name"""

    def initial(user):
        words = user.full_name.split()
        return words[-1][0].casefold() if len(words) > 1 else None

    mine = initial(person)
    if mine is not None and sum(initial(user) == mine for user in same) == 1:
        return f"{person.get_short_name()} {person.full_name.split()[-1][0]}."
    return str(person)


def display_names(viewer):
    """``{person's ID: name}`` for everybody the viewer may know
    (``known_people()``), computed once per viewer object (a request's user,
    the recipient of a mail); one query. People the viewer may not know and
    nobody (``None``) get no entry: ``display_name()`` falls back."""
    if viewer is None or not viewer.is_authenticated:
        return {}
    names = getattr(viewer, "_display_names", None)
    if names is None:
        from biwak.organizations.people import known_people

        people = list(
            known_people(viewer)
            .select_related(None)
            .only("full_name", "short_name", "email")
            .order_by()
        )
        by_name = defaultdict(list)
        for person in people:
            by_name[person.get_short_name().casefold()].append(person)
        names = {}
        for same in by_name.values():
            for person in same:
                names[person.pk] = (
                    person.get_short_name()
                    if len(same) == 1
                    else short_label(person, same)
                )
        viewer._display_names = names
    return names


def display_name(person, viewer):
    return display_names(viewer).get(person.pk) or person.get_short_name()
