# Check-ins

A check-in asks chosen people the same question on a schedule ("What
are you working on this week?") and collects the answers in one place.
It's mostly used for the team itself.

## Setting one up

Staff open **Check-ins** on the project's page and choose "New
check-in":

- **Question**: the text people see.
- **Asked**: how often (daily, weekly, monthly, yearly, with an
  interval and weekdays), **First asked on** and **Time of day**, in
  the installation's time zone. 09:00 stays 09:00 on the wall clock
  through the changes to and from daylight saving time.
- **Visible to clients**: only then can clients be asked and see the
  answers ([Clients](clients.md)).
- **People asked**: who gets the question. Type a name, or a team's to
  add its members at once; clients are offered only while "Visible to
  clients" is ticked. Deactivated people and people who can't see the
  question any more (they left the project, or clients once it's
  internal) stay in the list until you take them out, but aren't asked
  and can't be added. The question's page marks them "(inactive)" or
  "(not asked: can't see the check-in)"; back, they're asked again.

"Pause" stops the asking and "Resume" starts it again; dates missed
while paused aren't asked afterwards. Questions that were paused (for
example after an import) can be resumed together on the project's
check-ins page with "Resume all paused".

## Answering

When the question is due, everybody asked gets a mail with a link to
the answer form. Anybody who can see the question may answer too, asked
or not ("Answer" on the question's page). Open the link, write your answer (Markdown, with
mentions and attachments) and "Save the answer". When the mail says
"Reply to this mail to answer.", replying to it answers too. Answering again changes your answer. A check-in waiting for
you shows on Home and on the project's page.

There are no reminders: the mail is the only time you are asked. Who
hasn't answered yet is listed on the question's page. Somebody away
(out of office, see [Notifications](notifications.md)) isn't asked that
time and isn't missing.

## Reading the answers

The question's page shows the latest round's answers, newest first,
with who hasn't answered yet, and older rounds below ("Show older").
Every answer has comments and reactions. A person's name leads to everything they
answered over time.

## Mails about answers

The question's **subscribers** hear about the answers; at first they
are the people asked and whoever created the question. Like on any item,
"Subscribe" and "Unsubscribe" on the question's page change it, and
"Manage…" adds others. Your notification level doesn't matter here:
subscribed means you hear about the answers. Answering subscribes you to
your own answer (comments on it reach you), not to everybody's.

Each subscriber chooses on the question's page how they hear about
answers ("Mails about answers"):

- **one summary the morning after** (the default): one mail at 07:00
  with all the answers of that round (while you're away or in quiet
  hours it waits; it doesn't come if you chose another way or
  unsubscribed meanwhile);
- **a mail for each answer**;
- **no mails**.

With "No mails" in your settings you get no check-in mails at all,
neither the questions nor the answers; the check-ins waiting for you
show on Home.
