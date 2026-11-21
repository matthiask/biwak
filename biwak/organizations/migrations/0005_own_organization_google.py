from django.db import migrations


# As in biwak/organizations/models.py when this was written
FREE_MAIL_DOMAINS = {
    "aol.com",
    "bluewin.ch",
    "gmail.com",
    "gmx.at",
    "gmx.ch",
    "gmx.de",
    "gmx.net",
    "googlemail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "mac.com",
    "me.com",
    "msn.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "sunrise.ch",
    "t-online.de",
    "web.de",
    "yahoo.com",
}


def own_organization_google(apps, schema_editor):
    """Google sign-in for staff (specs/access.md) becomes the own
    organization's setting: single sign-on allowed, Google (specs/sso.md,
    decided 2026-11-21: nothing changes for staff). Google counts only for
    the organization's domains (its ``hd`` claim), so without domains the
    own organization gets those of its active staff's addresses, unless
    another organization has them already."""
    Organization = apps.get_model("organizations", "Organization")
    User = apps.get_model("accounts", "User")
    own = Organization.objects.filter(is_own=True).first()
    if own is None:
        return
    own.signin = "sso_allowed"
    own.idp = "google"
    if not own.domains:
        taken = {
            domain
            for domains in Organization.objects.exclude(pk=own.pk).values_list(
                "domains", flat=True
            )
            for domain in domains
        }
        domains = []
        for email in User.objects.filter(
            organization=own, is_client=False, is_active=True
        ).values_list("email", flat=True):
            domain = email.rpartition("@")[2].strip().rstrip(".").lower()
            if (
                domain
                and domain not in FREE_MAIL_DOMAINS
                and domain not in taken
                and domain not in domains
            ):
                domains.append(domain)
        own.domains = sorted(domains)
        # Staff's Google sign-in counts only for these: check them after
        # deploying (specs/sso.md, "Production setup")
        print(
            "\n  The own organization's domains for Google sign-in, from its"
            f" staff's addresses: {', '.join(own.domains) or 'none'}."
            " Check them on its page."
        )
    own.save()


class Migration(migrations.Migration):
    dependencies = [("organizations", "0004_signin")]

    operations = [
        migrations.RunPython(own_organization_google, migrations.RunPython.noop)
    ]
