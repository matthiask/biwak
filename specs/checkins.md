# Check-ins

A question asked automatically on a schedule to chosen people, answers
collected in one place with comments: "How are you, what are you working
on this week?", "Read any good books lately?". Used heavily for the team
itself, less for client projects.

- **Question**: text, schedule (RRULE with time of day, same machinery as
  recurring to-dos), time zone, the people asked, paused or not, visible
  to clients or not.
- **Each occurrence** sends the question by mail (and shows it in the
  app as due); people answer in the app or by replying to the mail
  (`notifications.md`).
- **Answers** are items with rich text, comments and attachments,
  grouped per occurrence (by date), newest first. One answer per person
  and occurrence; editing is possible.
- People can skip an occurrence. A reminder goes to those who haven't
  answered, once, a configurable time later.
- Per question, people choose whether they get a mail for each answer, a
  digest, or nothing.
- The question's page shows the latest occurrence's answers and who
  hasn't answered yet; a person's answers over time are one click away.

## Tests

Schedules across daylight saving time changes and time zones; pausing
and resuming; answering by mail to an older occurrence.
