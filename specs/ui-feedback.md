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
- My counter now says 7 unread (which is correct), but I only have 5 entries (because of grouping). So, it might instead say how many entries I have?
- There seems to be a double divider between unread and read lantern items, that looks like a bug.


## Round 3

Ad hoc.

## Round 4

- "Sign out" in menu. It's understood that this only does the log out here.
- Instead of the help text, add a button to sign out immediately on the sessions card. "Sign out here" or something like that.
- The to do checkbox is misaligned.
- "Add a to-do" and "New group" should be on the same line.
- "Show to clients" is a potentially destructive action and needs a warning modal. One click isn't enough for revealing potentially damaging information.
- The grouping in the activity log is nice. It could go further I think, and for example group conversation happening within an hour or more and show them together. Stop collapsing items, I'd like to try going without <details> here. The individual items themselves should be indented though in groups.
- todo_grouping shouldn't be a model field but a restored filter for the filter form. The ordering can go into the filter as well.

## Round 5

- The detail view of to dos could use more cards, for example for title and description. It seems a bit unstructured now (even though it isn't). Same for docs.
- The project to do list can also be linked from the project overview since that actually exists and makes sense. To Dos by list, or to dos by due date.
