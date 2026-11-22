# ruff: noqa: FBT003
"""Recorded shapes of the Basecamp 4 API with made-up content (for the tests)

The shapes come from the API's documentation (github.com/basecamp/bc3-api,
sections/*.md); every name, text, address and ID is made up. ``FakeClient``
answers like ``BasecampClient`` without a network.
"""

import base64
import copy
import io
import random
import urllib.parse

from PIL import Image, ImageDraw

from biwak.importer.client import NotFound


ACCOUNT = 1000
PROJECT = 100
BASE = f"https://3.basecampapi.com/{ACCOUNT}"
APP = f"https://3.basecamp.com/{ACCOUNT}"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff"
    b"?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _png(image):
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def generated_image():
    """Like Basecamp's own: a flat colored square with white initials"""
    image = Image.new("RGB", (200, 200), (0x2F, 0x80, 0xED))
    ImageDraw.Draw(image).text((70, 90), "AE", fill="white", font_size=60)
    return _png(image)


def photo_image():
    """A noisy "photo": the corners differ, no color dominates"""
    rng = random.Random(1)
    image = Image.new("RGB", (200, 200))
    image.putdata([tuple(rng.randrange(256) for _ in range(3)) for _ in range(40000)])
    return _png(image)


def detailed_image():
    """Flat corners, but a lot of detail in the middle"""
    rng = random.Random(2)
    image = Image.new("RGB", (200, 200), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    for _ in range(1500):
        x, y = rng.randrange(20, 180), rng.randrange(20, 180)
        draw.rectangle(
            (x, y, x + 12, y + 12), fill=tuple(rng.randrange(256) for _ in range(3))
        )
    return _png(image)


def avatar_url(pid):
    return f"{BASE}/people/{pid}/avatar"


def sgid(pid):
    """What Basecamp's signed global IDs of people look like inside: Ruby's
    marshalled data around ``gid://bc3/Person/ID``"""
    raw = f'\x04\x08{{\x06I"\x0b_rails\x06:\x06ET{{\x07gid://bc3/Person/{pid}?expires_in\x06'
    return base64.b64encode(raw.encode()).decode() + "--" + "0" * 40


def person(pid, name, email, *, client=False, admin=False, company=None):
    """The shape of ``GET /people.json``"""
    return {
        "id": pid,
        "attachable_sgid": sgid(pid),
        "name": name,
        "personable_type": "User",
        "title": None,
        "tagline": None,
        "location": None,
        "created_at": "2026-01-02T08:00:00.000Z",
        "updated_at": "2026-01-02T08:00:00.000Z",
        "email_address": email,
        "bio": None,
        "admin": admin,
        "owner": admin,
        "client": client,
        "employee": not client,
        "time_zone": "Europe/Zurich",
        # ``people.json`` lists it as null, only ``people/ID.json`` has it
        "avatar_url": None,
        "company": company,
        "can_ping": True,
        "can_manage_projects": not client,
        "can_manage_people": admin,
        "can_access_timesheet": False,
        "can_access_hill_charts": False,
    }


ADA = person(
    1,
    "Ada Example",
    "ada@example.org",
    admin=True,
    company={"id": 9, "name": "Example Team"},
)
BOB = person(
    2, "Bob Example", "bob@example.org", company={"id": 9, "name": "Example Team"}
)
CLEO = person(
    3,
    "Cleo Example",
    "cleo@example.org",
    client=True,
    company={"id": 10, "name": "Example Client Ltd"},
)
# Not on the project, mentioned only
EVE = person(4, "Eve Example", "eve@example.org")


def recording(
    rid, type_, title, creator, created, *, parent=None, visible=False, **extra
):
    """The envelope every recording has"""
    path = {
        "Todo": "todos",
        "Todolist": "todolists",
        "Message": "messages",
        "Document": "documents",
        "Upload": "uploads",
        "Vault": "vaults",
        "Comment": "comments",
        "Question": "questions",
        "Kanban::Card": "card_tables/cards",
    }.get(type_, "recordings")
    return {
        "id": rid,
        "status": "active",
        "visible_to_clients": visible,
        "created_at": created,
        "updated_at": created,
        "title": title,
        "inherits_status": True,
        "type": type_,
        "url": f"{BASE}/buckets/{PROJECT}/{path}/{rid}.json",
        "app_url": f"{APP}/buckets/{PROJECT}/{path}/{rid}",
        "bookmark_url": f"{BASE}/my/bookmarks/x{rid}.json",
        "subscription_url": f"{BASE}/buckets/{PROJECT}/recordings/{rid}/subscription.json",
        "comments_count": 0,
        "parent": parent,
        "bucket": {"id": PROJECT, "name": "Camp kitchen", "type": "Project"},
        "creator": creator,
        **extra,
    }


def file_entry(eid, name, content_type="image/png"):
    """An entry of ``content_attachments`` (sections/rich_text.md)"""
    return {
        "id": eid,
        "sgid": f"file-sgid-{eid}",
        "filename": name,
        "content_type": content_type,
        "byte_size": len(PNG),
        "download_url": f"{BASE}/blobs/{eid}/download/{name}",
        "width": 1,
        "height": 1,
        "previewable": True,
    }


def mention(person_):
    return (
        f'<bc-attachment sgid="{person_["attachable_sgid"]}"'
        ' content-type="application/vnd.basecamp.mention"><figure>'
        f'<img class="avatar" src="{BASE}/avatar"><figcaption>{person_["name"].split()[0]}'
        "</figcaption></figure></bc-attachment>"
    )


def image(entry):
    return (
        f'<bc-attachment sgid="{entry["sgid"]}" content-type="{entry["content_type"]}"'
        f' url="{BASE}/x" href="{BASE}/y" filename="{entry["filename"]}">'
        f'<figure><img src="{BASE}/x"><figcaption>{entry["filename"]}</figcaption>'
        "</figure></bc-attachment>"
    )


def make_data():
    """Every kind of the mapping; the tests change what they need"""
    d = {}
    board = {"id": 200, "title": "Message Board", "type": "Message::Board"}
    todoset = {"id": 300, "title": "To-dos", "type": "Todoset"}
    vault = {"id": 400, "title": "Docs & Files", "type": "Vault"}
    questionnaire = {"id": 500, "title": "Automatic Check-ins", "type": "Questionnaire"}

    dock = [
        {"id": 200, "title": "Message Board", "name": "message_board", "enabled": True},
        {"id": 300, "title": "To-dos", "name": "todoset", "enabled": True},
        {"id": 400, "title": "Docs & Files", "name": "vault", "enabled": True},
        {"id": 700, "title": "Calendar", "name": "schedule", "enabled": True},
        {"id": 800, "title": "Chat", "name": "chat", "enabled": True},
        {"id": 600, "title": "Card Table", "name": "kanban_board", "enabled": True},
        {
            "id": 500,
            "title": "Automatic Check-ins",
            "name": "questionnaire",
            "enabled": True,
        },
        {"id": 900, "title": "Email Forwards", "name": "inbox", "enabled": False},
    ]
    d[f"/projects/{PROJECT}.json"] = {
        "id": PROJECT,
        "status": "active",
        "created_at": "2026-01-05T09:00:00.000Z",
        "updated_at": "2026-03-01T09:00:00.000Z",
        "name": "Camp kitchen",
        "description": "Cooking for the summer camp.",
        "purpose": "topic",
        "clients_enabled": True,
        "all_access": False,
        "url": f"{BASE}/projects/{PROJECT}.json",
        "app_url": f"{APP}/projects/{PROJECT}",
        "dock": dock,
    }
    d[f"/projects/{PROJECT}/people.json"] = [ADA, BOB, CLEO]
    for person_ in (ADA, BOB, CLEO):
        d[f"/people/{person_['id']}.json"] = {
            **person_,
            "avatar_url": avatar_url(person_["id"]),
        }

    # To-do lists ---------------------------------------------------------
    plan = recording(
        301,
        "Todolist",
        "Kitchen plan",
        ADA,
        "2026-01-06T10:00:00.000Z",
        parent=todoset,
        visible=True,
        position=1,
        description=f"<div>What we cook, {mention(EVE)} knows the rest.</div>",
        description_attachments=[],
        completed=False,
        name="Kitchen plan",
        groups_url=f"{BASE}/todolists/301/groups.json",
    )
    budget = recording(
        302,
        "Todolist",
        "Budget",
        ADA,
        "2026-01-06T11:00:00.000Z",
        parent=todoset,
        position=2,
        description="",
        description_attachments=[],
    )
    old = recording(
        303,
        "Todolist",
        "Old ideas",
        BOB,
        "2026-01-06T12:00:00.000Z",
        parent=todoset,
        position=3,
        status="archived",
        description="",
        description_attachments=[],
    )
    d["/todosets/300/todolists.json"] = [budget, plan]
    d["/todosets/300/todolists.json?status=archived"] = [old]

    def todo(tid, title, creator, created, parent, *, visible=False, **extra):
        return recording(
            tid,
            "Todo",
            title,
            creator,
            created,
            parent={"id": parent, "type": "Todolist", "title": "x"},
            visible=visible,
            **(
                {
                    "description": "",
                    "description_attachments": [],
                    "completed": False,
                    "content": title,
                    "starts_on": None,
                    "due_on": None,
                    "assignees": [],
                    "completion_subscribers": [],
                    "steps": [],
                }
                | extra
            ),
        )

    feed = todo(
        3011,
        "Buy giraffe food",
        ADA,
        "2026-01-07T08:00:00.000Z",
        301,
        visible=True,
        description=f'<div>Ask {mention(BOB)} about prices.<br>See <a href="{APP}/buckets/{PROJECT}/messages/2001">the announcement</a>.</div>',
        due_on="2026-06-01",
        assignees=[BOB, CLEO],
        comments_count=2,
    )
    feed["updated_at"] = "2026-01-09T08:00:00.000Z"
    done = todo(
        3012,
        "Pick a camp date",
        BOB,
        "2026-01-07T09:00:00.000Z",
        301,
        visible=True,
        completed=True,
        completion={"created_at": "2026-01-08T16:30:00.000Z", "creator": ADA},
        assignees=[ADA],
    )
    leaky = todo(
        3013,
        "Raise the rate for Cleo",
        BOB,
        "2026-01-07T10:00:00.000Z",
        301,
        visible=False,
    )
    grouped = todo(
        3015, "Peel potatoes", ADA, "2026-01-07T11:00:00.000Z", 3014, visible=True
    )
    d["/todolists/301/todos.json"] = [feed, leaky]
    d["/todolists/301/todos.json?completed=true"] = [done]
    group = recording(
        3014,
        "Todolist",
        "Week 1",
        ADA,
        "2026-01-06T10:30:00.000Z",
        parent={"id": 301, "type": "Todolist", "title": "Kitchen plan"},
        visible=True,
        position=1,
        description="",
        description_attachments=[],
        group_position_url=f"{BASE}/todolists/groups/3014/position.json",
    )
    d["/todolists/301/groups.json"] = [group]
    d["/todolists/3014/todos.json"] = [grouped]

    logo = file_entry(7001, "menu.png")
    secret = todo(
        3021,
        "Negotiate the price",
        ADA,
        "2026-01-08T08:00:00.000Z",
        302,
        description=f"<div>Offer attached.{image(logo)}</div>",
        description_attachments=[logo],
        assignees=[ADA],
    )
    d["/todolists/302/todos.json"] = [secret]
    d["/todolists/303/todos.json?status=archived"] = [
        todo(
            3031,
            "Whale watching",
            BOB,
            "2026-01-08T09:00:00.000Z",
            303,
            status="archived",
        )
    ]

    # Archived recordings other than to-dos and lists: found by the
    # recordings' listing, not imported
    def archived(rid, type_, title):
        return recording(
            rid, type_, title, BOB, "2026-01-02T09:00:00.000Z", status="archived"
        )

    for type_, rid, title in [
        ("Message", 9001, "Old announcement"),
        ("Document", 9002, "Old notes"),
        ("Upload", 9003, "old.png"),
        ("Question", 9004, "Last year's question"),
    ]:
        d[
            f"/projects/recordings.json?bucket={PROJECT}&status=archived&type={type_}"
        ] = [archived(rid, type_, title)]

    # Comments and subscriptions -------------------------------------------
    def comment(cid, text, creator, created, parent):
        return recording(
            cid,
            "Comment",
            f"Re: {parent['title']}",
            creator,
            created,
            parent=parent,
            content=text,
            content_attachments=[],
        )

    p3011 = {"id": 3011, "type": "Todo", "title": "Buy giraffe food"}
    d["/recordings/3011/comments.json"] = [
        comment(
            8001, "<div>Done by Friday.</div>", BOB, "2026-01-10T08:00:00.000Z", p3011
        ),
        comment(
            8002,
            f"<div>Thanks {mention(ADA)}!</div>",
            CLEO,
            "2026-01-11T08:00:00.000Z",
            p3011,
        ),
    ]
    d["/recordings/3011/subscription.json"] = {
        "subscribed": True,
        "count": 2,
        "subscribers": [ADA, BOB],
    }

    # Card table ------------------------------------------------------------
    table = {"id": 600, "title": "Planning board", "type": "Kanban::Board"}
    columns = [
        recording(
            6001,
            "Kanban::Triage",
            "Triage",
            ADA,
            "2026-01-12T08:00:00.000Z",
            parent=table,
            description=None,
            cards_count=1,
        ),
        recording(
            6002,
            "Kanban::Column",
            "Cooking",
            ADA,
            "2026-01-12T08:01:00.000Z",
            parent=table,
            description=None,
            cards_count=0,
        ),
        recording(
            6003,
            "Kanban::DoneColumn",
            "Done",
            ADA,
            "2026-01-12T08:02:00.000Z",
            parent=table,
            description=None,
            cards_count=1,
        ),
    ]
    d["/card_tables/600.json"] = recording(
        600,
        "Kanban::Board",
        "Planning board",
        ADA,
        "2026-01-12T07:00:00.000Z",
        lists=columns,
        wormholes=[],
    )

    def card(cid, title, column, **extra):
        return recording(
            cid,
            "Kanban::Card",
            title,
            ADA,
            "2026-01-13T08:00:00.000Z",
            parent={"id": column, "type": "Kanban::Column", "title": "x"},
            **(
                {
                    "description": "",
                    "description_attachments": [],
                    "completed": False,
                    "content": title,
                    "due_on": None,
                    "assignees": [],
                    "completion_subscribers": [],
                    "comment_count": 0,
                    "steps": [],
                }
                | extra
            ),
        )

    d["/card_tables/lists/6001/cards.json"] = [
        card(
            60011,
            "New menu",
            6001,
            description="<div>Think about the menu</div>",
            steps=[
                {
                    "id": 1,
                    "title": "Find inspiration",
                    "completed": True,
                    "assignees": [],
                    "due_on": None,
                },
                {
                    "id": 2,
                    "title": "Write it down",
                    "completed": False,
                    "assignees": [],
                    "due_on": None,
                },
            ],
        )
    ]
    d["/card_tables/lists/6002/cards.json"] = []
    d["/card_tables/lists/6003/cards.json"] = [
        card(
            60031,
            "Order pots",
            6003,
            completed=True,
            completion={"created_at": "2026-01-14T08:00:00.000Z", "creator": BOB},
        )
    ]

    # Messages ----------------------------------------------------------------
    announcement = recording(
        2001,
        "Message",
        "We have a camp",
        ADA,
        "2026-01-15T08:00:00.000Z",
        parent=board,
        visible=True,
        comments_count=1,
        subject="We have a camp",
        content=f'<div>Hello {mention(CLEO)}!<br><br>The plan: <a href="{APP}/buckets/{PROJECT}/todos/3011#__recording_1">food</a></div>',
        content_attachments=[],
        category={"id": 5, "name": "Announcement", "icon": "\U0001f4e2"},
    )
    internal = recording(
        2002,
        "Message",
        "Prices",
        CLEO,
        "2026-01-16T08:00:00.000Z",
        parent=board,
        visible=False,
        subject="Prices",
        content="<div>Only for us</div>",
        content_attachments=[],
    )
    d["/message_boards/200/messages.json"] = [internal, announcement]
    d["/recordings/2001/comments.json"] = [
        comment(
            8101,
            "<div>Great</div>",
            BOB,
            "2026-01-16T09:00:00.000Z",
            {"id": 2001, "type": "Message", "title": "We have a camp"},
        )
    ]
    d["/recordings/2001/subscription.json"] = {
        "subscribed": True,
        "count": 3,
        "subscribers": [ADA, BOB, CLEO],
    }

    # Docs & Files ----------------------------------------------------------------
    def doc(did, title, parent, visible, creator=ADA, content="<div>Text</div>"):
        return recording(
            did,
            "Document",
            title,
            creator,
            "2026-02-01T08:00:00.000Z",
            parent=parent,
            visible=visible,
            content=content,
            content_attachments=[],
        )

    def upload(uid, name, parent, visible, creator=ADA):
        return recording(
            uid,
            "Upload",
            name,
            creator,
            "2026-02-02T08:00:00.000Z",
            parent=parent,
            visible=visible,
            description="<div>Check this</div>",
            description_attachments=[],
            comments_count=1 if uid == 4102 else 0,
            content_type="image/png",
            byte_size=len(PNG),
            filename=name,
            width=1,
            height=1,
            download_url=f"{BASE}/buckets/{PROJECT}/uploads/{uid}/download/{name}",
        )

    def folder(fid, title, parent, visible):
        return recording(
            fid,
            "Vault",
            title,
            ADA,
            "2026-02-03T08:00:00.000Z",
            parent=parent,
            visible=visible,
            documents_count=0,
            uploads_count=0,
            vaults_count=0,
            position=fid,
        )

    d["/vaults/400/vaults.json"] = [
        folder(410, "Public", vault, True),
        folder(420, "Private", vault, False),
        folder(430, "Mixed", vault, True),
    ]
    d["/vaults/400/documents.json"] = [
        doc(4001, "Shopping list", vault, False),
        doc(
            4002, "Camp rules", vault, True, content=f"<div>Rules {mention(EVE)}</div>"
        ),
    ]
    d["/vaults/400/uploads.json"] = [upload(4003, "plan.png", vault, False)]
    p410 = {"id": 410, "type": "Vault", "title": "Public"}
    d["/vaults/410/vaults.json"] = []
    d["/vaults/410/documents.json"] = [doc(4101, "Public doc", p410, True)]
    d["/vaults/410/uploads.json"] = [upload(4102, "map.png", p410, True)]
    d["/recordings/4102/comments.json"] = [
        comment(
            8201,
            "<div>Nice map</div>",
            CLEO,
            "2026-02-04T08:00:00.000Z",
            {"id": 4102, "type": "Upload", "title": "map.png"},
        )
    ]
    p420 = {"id": 420, "type": "Vault", "title": "Private"}
    d["/vaults/420/vaults.json"] = [folder(421, "Deeper", p420, False)]
    d["/vaults/420/documents.json"] = []
    d["/vaults/420/uploads.json"] = [upload(4201, "salaries.png", p420, False)]
    d["/vaults/421/vaults.json"] = []
    d["/vaults/421/documents.json"] = [
        doc(4211, "Deep doc", {"id": 421, "type": "Vault", "title": "Deeper"}, False)
    ]
    d["/vaults/421/uploads.json"] = []
    p430 = {"id": 430, "type": "Vault", "title": "Mixed"}
    d["/vaults/430/vaults.json"] = []
    d["/vaults/430/documents.json"] = [
        doc(4301, "Internal in a public folder", p430, False)
    ]
    d["/vaults/430/uploads.json"] = []

    # Check-ins -------------------------------------------------------------------
    def question(qid, title, visible, schedule):
        return recording(
            qid,
            "Question",
            title,
            ADA,
            "2026-02-10T08:00:00.000Z",
            parent=questionnaire,
            visible=visible,
            paused=False,
            schedule=schedule,
            answers_count=2,
        )

    weekdays = {
        "frequency": "every_day",
        "days": [1, 2, 3, 4, 5],
        "hour": 9,
        "minute": 0,
        "week_instance": None,
        "week_interval": None,
        "month_interval": None,
        "start_date": "2026-02-11",
        "duration": None,
        "end_date": None,
    }
    monthly = weekdays | {
        "frequency": "every_month",
        "days": [],
        "start_date": "2026-02-05",
    }
    d["/questionnaires/500/questions.json"] = [
        question(5001, "What did you cook today?", True, weekdays),
        question(5002, "Any worries?", False, monthly),
    ]

    def answer(aid, question_, who, day, text, **extra):
        return recording(
            aid,
            "Question::Answer",
            f"Answer to “{question_['title']}”",
            who,
            f"{day}T17:00:00.000Z",
            parent=question_,
            content=text,
            content_attachments=[],
            group_on=day,
            **extra,
        )

    q1 = {"id": 5001, "type": "Question", "title": "What did you cook today?"}
    q2 = {"id": 5002, "type": "Question", "title": "Any worries?"}
    d["/questions/5001/answers.json"] = [
        answer(5101, q1, ADA, "2026-02-12", "<div>Soup</div>", visible_to_clients=True),
        answer(
            5102,
            q1,
            BOB,
            "2026-02-12",
            '<div>Bread for <a href="https://example.org/x">all</a></div>',
            visible_to_clients=True,
        ),
        answer(
            5103, q1, ADA, "2026-02-13", "<div>Pasta</div>", visible_to_clients=True
        ),
    ]
    d["/questions/5002/answers.json"] = [
        answer(5201, q2, BOB, "2026-02-05", "<div>The stove</div>")
    ]

    d["/my/bookmarks.json"] = [
        {
            "id": 1,
            "created_at": "2026-02-20T08:00:00.000Z",
            "updated_at": "2026-02-20T08:00:00.000Z",
            "recording": {"id": 2001, "type": "Message", "title": "We have a camp"},
        },
        {
            "id": 2,
            "created_at": "2026-02-20T08:00:00.000Z",
            "updated_at": "2026-02-20T08:00:00.000Z",
            "recording": {"id": 777, "type": "Message", "title": "Another project"},
        },
    ]
    d["/my/profile.json"] = ADA

    files = {
        avatar_url(ADA["id"]): generated_image(),
        avatar_url(BOB["id"]): photo_image(),
        avatar_url(CLEO["id"]): detailed_image(),
        f"{BASE}/blobs/7001/download/menu.png": PNG,
        f"{BASE}/buckets/{PROJECT}/uploads/4003/download/plan.png": PNG + b"1",
        f"{BASE}/buckets/{PROJECT}/uploads/4102/download/map.png": PNG + b"2",
        f"{BASE}/buckets/{PROJECT}/uploads/4201/download/salaries.png": PNG + b"3",
    }
    return d, files


class FakeClient:
    """``BasecampClient``'s ``get()``, ``paginate()``, ``download()`` and
    ``archive_project()`` over recorded data, counting the requests"""

    def __init__(self, data=None, files=None):
        made, made_files = make_data()
        self.data = copy.deepcopy(made if data is None else data)
        self.files = made_files if files is None else files
        self.requests = []
        self.downloads = []
        self.archived_projects = []
        # Called with the path of each request, to fail in the middle
        self.on_request = None

    def _lookup(self, path, params):
        self.requests.append((path, params))
        if self.on_request:
            self.on_request(path)
        key = path + (
            "?" + urllib.parse.urlencode(sorted(params.items())) if params else ""
        )
        try:
            return copy.deepcopy(self.data[key])
        except KeyError:
            raise NotFound(key) from None

    def get(self, path, **params):
        return self._lookup(path, params)

    def paginate(self, path, **params):
        found = self._lookup(path, params)
        # A collection without that variant is empty, not missing
        return iter(found)

    def archive_project(self, project_id):
        self.archived_projects.append(project_id)

    def download(self, url, *, accept=None):
        self.downloads.append(url)
        try:
            return self.files[url]
        except KeyError:
            raise NotFound(url) from None
