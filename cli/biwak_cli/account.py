"""Logging in and out, who you are and your settings"""

import os

import click

from biwak_cli.core import (
    _send,
    base_url,
    browser_login,
    cli,
    current,
    echo_json,
    json_option,
    read_config,
    request,
    save_login,
    terminate,
    write_config,
)


@cli.command()
@click.argument("url", required=False)
@click.option("--read", "access", flag_value="read", help="biwak may only read.")
@click.option("--write", "access", flag_value="write", help="biwak may read and write.")
@click.option(
    "--token",
    "paste_token",
    is_flag=True,
    help="Paste a token from the API tokens page (computers without a browser).",
)
def login(url, access, paste_token):
    """Authorize biwak in your name through the browser"""
    if not (url := base_url(url or read_config().get("url"))):
        terminate("Which Biwak? Run `biwak login URL --read` or `--write`.")
    if paste_token:
        save_login(url, click.prompt("API token", hide_input=True).strip())
    elif not access:
        terminate("Choose the access: `biwak login --read` or `--write`.")
    else:
        browser_login(url, access)
    me = request("GET", "me/")
    click.echo(f"Logged in as {me['name']} ({me['access']}).")


@cli.command()
def logout():
    """Revoke biwak's token and forget it"""
    url, token = current()
    response = _send("DELETE", url, "tokens/current/", token)
    config = read_config()
    write_config({"url": config.get("url")})
    if response.status_code in {200, 401}:
        click.echo(f"Logged out from {url}.")
    else:
        terminate("Forgot the token, but couldn't revoke it: see the API tokens page.")


@cli.group(invoke_without_command=True)
@json_option
@click.pass_context
def me(ctx, as_json):
    """Who you are and the token's access; `biwak me image` sets your
    profile image"""
    if ctx.invoked_subcommand is not None:
        return None
    data = request("GET", "me/")
    if as_json:
        return echo_json(data)
    kind = "client" if data["is_client"] else "staff"
    click.echo(f"{data['name']} <{data['email']}>, {kind}, {data['access']} access")
    return None


@me.command("image")
@click.argument("path", required=False, type=click.Path(exists=True, dir_okay=False))
@click.option("--remove", is_flag=True, help="Back to the drawn mark.")
@json_option
def me_image(path, remove, as_json):
    """Set your profile image to the JPEG, PNG or WebP at PATH (at most 5 MB;
    cut to a square in the middle), or remove it"""
    if remove == bool(path):
        terminate("Give a file, or --remove.")
    if remove:
        data = request("DELETE", "me/image/")
    else:
        with click.open_file(path, "rb") as file:
            data = request(
                "PUT",
                "me/image/",
                files={"image": (os.path.basename(path), file)},
            )
    if as_json:
        return echo_json(data)
    click.echo(
        "Removed your profile image."
        if remove
        else f"Your profile image: {data['image_url']}"
    )
    return None


LANGUAGES = {"auto": "", "de": "de", "en": "en"}


@cli.command()
@click.option(
    "--language",
    type=click.Choice(list(LANGUAGES)),
    help="The web interface's and the mails' language; auto follows the browser.",
)
@json_option
def settings(language, as_json):
    """Your preferences for the web interface; the options change them"""
    if language is not None:
        data = request("PUT", "me/", json={"language": LANGUAGES[language]})
    else:
        data = request("GET", "me/")
    if as_json:
        return echo_json(data)
    shortcuts = "on" if data["keyboard_shortcuts"] else "off"
    click.echo(f"Language: {data['language'] or 'auto'}")
    click.echo(f"Theme: {data['theme']}, accent: {data['accent']}")
    click.echo(f"Single-key shortcuts: {shortcuts}")
    return None
