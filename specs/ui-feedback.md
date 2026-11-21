# Collected UI feedback found while testing the project


## Round 1

- New list doesn't have to be visible always, it can just be a button like in messages.
- A modal form (like Governance) would be super nice here. Generally, more small forms could be placed into modals so that we don't lose context.
- Similarly, "New group" doesn't need to be an edit field which we always see.
- Overdue to dos aren't marked specially, they could receive a badge or something of the sort
- The notification setting at the bottom of the list could go into a "More" menu and into a modal which says that this is about notifications.
- The to do form doesn't need to show repeating options when the to do doesn't repeat. (Repeats until and repeats left -- those two could be folded into the rest of the options, or not?
- Basecamp shows the todo without editing UI when navigating to a detail page. CLicking into the text starts the editing. I actually like that. It does condense the UI a lot. And then, the reaction button could also be in the correct place from the start, and titles wouldn't have to repeat etc. This would also make it less likely that someone is editing the note which disables ticking off items.
- The assignees list can get really long when we have dozens of people in a project. Pills per assignee with an X to remove and an autocompletion widget (opens on click and when typing) would probably work better.
- The "move to" UI doesn't have to be always there, it can go into the more menu and a modal I think, trashing as well.
- I like the way the archive is implemented on the start page (Project list). With some htmx it would be even better.

## Round 2

- Archiving projects doesn't have to be accessible from the list.
- I'm unsure about the client badge in the activity list.
- The color picker for projects shouldn't use a dropdown, but a radio style input with colored circles. The name is not important, the color is.
- Settings: The list of sign-in subpages (passkeys, sessions, API tokens) doesn't look like menu items to me. I wonder if we shouldn't inline passkeys and sessions right there, and make API tokens a separate page. Or reorganize this some other way.
- Sessions: Is logging out single sessions possible? What does the "Sign Out" button do, end all sessions? This isn't clear enough right now. The thead is missing a cell.
- Filters should autosubmit the form I think, like in Governance.
- We will have a few Moritzes in Staff even, so we should probably find a way to differentiate them automatically. They do have different last names, so maybe that's enough when the people images or circles land.
- My To Do: I think the default grouping should be: Project, List, Group. By due date would be a different view, or a different ordering.
- Workbench (~/projects/sites/workbench) restores filters when navigating to the page again. I think I'd like that here as well.
- The "Me" menu should use the profile image.
- The items in the .wb-facts line on to dos isn't vertically aligned properly.
- It should be clear which lantern items have already been viewed.
- The lantern can use more horizonal space with all the content it has.
- my counter now says 7 unread (which is correct), but i only have 5 entries (because of grouping). so, it might instead say how many entries i have?
- there seems to be a double divider between unread and read lantern items, that looks like a bug.


## round 3

ad hoc.

## round 4

spec: `ui-round-4.md` (built 2026-11-21).

- "sign out" in menu. it's understood that this only does the log out here.
- instead of the help text, add a button to sign out immediately on the sessions card. "sign out here" or something like that.
- the to do checkbox is misaligned.
- "add a to-do" and "new group" should be on the same line.
- "show to clients" is a potentially destructive action and needs a warning modal. one click isn't enough for revealing potentially damaging information.
- the grouping in the activity log is nice. it could go further i think, and for example group conversation happening within an hour or more and show them together. stop collapsing items, i'd like to try going without <details> here. the individual items themselves should be indented though in groups.
- todo_grouping shouldn't be a model field but a restored filter for the filter form. the ordering can go into the filter as well.

## round 5

spec: `ui-round-5.md`.

- the detail view of to dos could use more cards, for example for title and description. it seems a bit unstructured now (even though it isn't). same for docs.
- the project to do list can also be linked from the project overview since that actually exists and makes sense. to dos by list, or to dos by due date.
- the "reset filters" button shouldn't sit at the bottom of the line, centered with the dropdowns would look better.
- basecamp has a "assigned by me" view, would it make sense to have something like this as well?

## round 6

Spec: `ui-round-6.md`.

- "add someone" on the people page of a project: the list can get really long really quickly. we need an autocomplete widget here, i think the best candidate is in workbench (good to copy since it's my code even though gpl)
- i'd expect a invite flow on the people page where i can invite (multiple) people, assign them to organizations, send out the mails and add them to projects directly (all to the same set of projects, if the projects aren't the same i'll start another round of invites). are we seeing invitations anywhere?
- On a to do item, I'm confused by notifications vs. subscribers. When I'm subscribing, I get notifications. The notification setting is important on projects or list, but on a single issue, when I'm a subscriber, I will be notified.
