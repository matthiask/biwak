"""What the API says about reactions; in the other parts' responses too"""

from ninja import Schema

from biwak.api_conventions import PersonOut, person_out
from biwak.reactions import operations


class ReactionOut(Schema):
    content: str
    count: int
    people: list[PersonOut]
    mine: bool


def reactions_out(item, comment, user, event=None):
    return [
        {
            "content": entry["content"],
            "count": entry["count"],
            "people": [person_out(person) for person in entry["people"]],
            "mine": entry["mine"],
        }
        for entry in operations.summary(item, comment, user, event)
    ]
