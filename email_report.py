import argparse
import os
import smtplib
import ssl
import subprocess
import sys

from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo


ARTIFACT_DIR = Path("artifacts")
REPORT_TIMEZONE = ZoneInfo("America/Detroit")


def require_env(name):
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Required environment variable is missing: {name}"
        )

    return value


def parse_recipients(value):
    value = value.replace(";", ",")

    recipients = [
        recipient.strip()
        for recipient in value.split(",")
        if recipient.strip()
    ]

    if not recipients:
        raise RuntimeError(
            "REPORT_TO_EMAIL does not contain a valid recipient."
        )

    return recipients


def run_weekly_report(provider):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    command = [
        sys.executable,
        "weekly_report.py",
        provider,
    ]

    print(
        f"Running Fantasy GM weekly report "
        f"for provider: {provider}"
    )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    output_parts = []

    if result.stdout:
        output_parts.append(
            result.stdout.rstrip()
        )

    if result.stderr:
        output_parts.append(
            "\n===== STDERR =====\n"
            + result.stderr.rstrip()
        )

    output = "\n".join(
        output_parts
    ).strip()

    if not output:
        output = (
            "(Fantasy GM produced no console output.)"
        )

    return result.returncode, output


def save_report(provider, output):
    ARTIFACT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = datetime.now(
        REPORT_TIMEZONE
    )

    timestamp = now.strftime(
        "%Y%m%d_%H%M%S_ET"
    )

    path = ARTIFACT_DIR / (
        f"{provider}_fantasy_report_{timestamp}.txt"
    )

    path.write_text(
        output,
        encoding="utf-8",
    )

    return path


def send_email(
    provider,
    return_code,
    report_text,
    report_path,
):
    smtp_host = require_env(
        "SMTP_HOST"
    )

    smtp_port = int(
        os.getenv(
            "SMTP_PORT",
            "587",
        ).strip()
        or "587"
    )

    smtp_username = os.getenv(
        "SMTP_USERNAME",
        "",
    ).strip()

    smtp_password = os.getenv(
        "SMTP_PASSWORD",
        "",
    )

    security = os.getenv(
        "SMTP_SECURITY",
        "",
    ).strip().lower()

    if not security:
        security = (
            "ssl"
            if smtp_port == 465
            else "starttls"
        )

    if security not in {
        "ssl",
        "starttls",
        "none",
    }:
        raise RuntimeError(
            "SMTP_SECURITY must be "
            "'ssl', 'starttls', or 'none'."
        )

    from_email = (
        os.getenv(
            "REPORT_FROM_EMAIL",
            "",
        ).strip()
        or smtp_username
    )

    if not from_email:
        raise RuntimeError(
            "REPORT_FROM_EMAIL is required "
            "when SMTP_USERNAME is empty."
        )

    recipients = parse_recipients(
        require_env(
            "REPORT_TO_EMAIL"
        )
    )

    status = (
        "PASS"
        if return_code == 0
        else "FAILED"
    )

    now = datetime.now(
        REPORT_TIMEZONE
    )

    subject = (
        f"[{status}] Fantasy GM "
        f"{provider.title()} Report - "
        f"{now.strftime('%A %m/%d/%Y %I:%M %p ET')}"
    )

    body = (
        f"Fantasy GM Automated Report\n"
        f"Provider: {provider.title()}\n"
        f"Status: {status}\n"
        f"Generated: "
        f"{now.strftime('%Y-%m-%d %I:%M %p ET')}\n"
        f"Exit code: {return_code}\n"
        f"\n"
        f"{report_text}\n"
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = ", ".join(
        recipients
    )
    message.set_content(
        body
    )

    context = (
        ssl.create_default_context()
    )

    if security == "ssl":
        with smtplib.SMTP_SSL(
            smtp_host,
            smtp_port,
            context=context,
            timeout=30,
        ) as server:

            if smtp_username:
                server.login(
                    smtp_username,
                    smtp_password,
                )

            server.send_message(
                message
            )

    else:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=30,
        ) as server:

            server.ehlo()

            if security == "starttls":
                server.starttls(
                    context=context
                )
                server.ehlo()

            if smtp_username:
                server.login(
                    smtp_username,
                    smtp_password,
                )

            server.send_message(
                message
            )

    print(
        "EMAIL DELIVERY: PASS "
        f"({len(recipients)} recipient(s))"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run Fantasy GM and email "
            "the resulting report."
        )
    )

    parser.add_argument(
        "provider",
        choices=[
            "sleeper",
            "yahoo",
        ],
    )

    args = parser.parse_args()

    return_code, output = (
        run_weekly_report(
            args.provider
        )
    )

    print()
    print(output)
    print()

    report_path = save_report(
        args.provider,
        output,
    )

    print(
        f"Report saved to: "
        f"{report_path}"
    )

    try:
        send_email(
            args.provider,
            return_code,
            output,
            report_path,
        )

    except Exception as exc:
        print(
            f"EMAIL DELIVERY: FAILED - "
            f"{exc}",
            file=sys.stderr,
        )

        return 1

    return return_code


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
