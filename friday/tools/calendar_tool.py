"""
Calendar & Reminder tools — create events, set reminders, list upcoming tasks.
Creates standard .ics calendar files (importable to Google Calendar, Outlook, Apple Calendar).
Reminders are persisted in the memory directory.
"""
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from friday.path_utils import memory_dir, workspace_dir


def _reminders_file() -> Path:
    return memory_dir() / "reminders.json"


def _load_reminders() -> list:
    f = _reminders_file()
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            return []
    return []


def _save_reminders(reminders: list):
    _reminders_file().write_text(json.dumps(reminders, indent=2))


def register(mcp):

    @mcp.tool()
    def create_calendar_event(
        title: str,
        start_datetime: str,
        end_datetime: str = "",
        description: str = "",
        location: str = "",
    ) -> str:
        """
        Create a calendar event and save it as an .ics file (importable to Google Calendar, Outlook, Apple Calendar).
        title: Event title/name.
        start_datetime: Start date and time in 'YYYY-MM-DD HH:MM' format (e.g. '2025-05-01 09:00').
        end_datetime: End date and time. Defaults to 1 hour after start.
        description: Optional event description.
        location: Optional event location.
        Use this when the user says 'create an event', 'add to calendar', 'schedule a meeting'.
        """
        try:
            # Parse start
            try:
                start_dt = datetime.strptime(start_datetime.strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                return "Invalid start_datetime format. Use 'YYYY-MM-DD HH:MM', e.g. '2025-05-01 14:30'."

            # Parse or generate end
            if end_datetime.strip():
                try:
                    end_dt = datetime.strptime(end_datetime.strip(), "%Y-%m-%d %H:%M")
                except ValueError:
                    return "Invalid end_datetime format. Use 'YYYY-MM-DD HH:MM'."
            else:
                end_dt = start_dt + timedelta(hours=1)

            if end_dt <= start_dt:
                return "End datetime must be after start datetime."

            # Format for ICS
            def fmt(dt: datetime) -> str:
                return dt.strftime("%Y%m%dT%H%M%S")

            event_uid = str(uuid.uuid4())
            now_str = fmt(datetime.utcnow())
            ics_content = "\r\n".join([
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//FRIDAY AI//EN",
                "CALSCALE:GREGORIAN",
                "METHOD:PUBLISH",
                "BEGIN:VEVENT",
                f"UID:{event_uid}",
                f"DTSTAMP:{now_str}Z",
                f"DTSTART:{fmt(start_dt)}",
                f"DTEND:{fmt(end_dt)}",
                f"SUMMARY:{title}",
                f"DESCRIPTION:{description}" if description else "",
                f"LOCATION:{location}" if location else "",
                "END:VEVENT",
                "END:VCALENDAR",
            ])
            ics_content = "\r\n".join(line for line in ics_content.split("\r\n") if line)

            safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip().replace(" ", "_")[:40]
            filename = f"event_{safe_title}_{start_dt.strftime('%Y%m%d_%H%M')}.ics"
            save_path = workspace_dir() / filename
            save_path.write_text(ics_content)

            return (
                f"Calendar event created: '{title}'\n"
                f"Starts : {start_dt.strftime('%A, %B %d %Y at %I:%M %p')}\n"
                f"Ends   : {end_dt.strftime('%A, %B %d %Y at %I:%M %p')}\n"
                f"File   : {save_path}\n"
                f"Import this .ics file into Google Calendar, Outlook, or Apple Calendar."
            )
        except Exception as e:
            return f"Error creating calendar event: {str(e)}"

    @mcp.tool()
    def add_reminder(text: str, remind_at: str) -> str:
        """
        Add a reminder that F.R.I.D.A.Y. will surface when you ask for upcoming reminders.
        text: What to remind you about.
        remind_at: When to remind you — 'YYYY-MM-DD HH:MM' format (e.g. '2025-05-01 09:00').
        Use this when the user says 'remind me to X', 'set a reminder for X'.
        """
        try:
            try:
                remind_dt = datetime.strptime(remind_at.strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                return "Invalid remind_at format. Use 'YYYY-MM-DD HH:MM', e.g. '2025-05-01 09:00'."

            reminders = _load_reminders()
            reminder = {
                "id": str(uuid.uuid4())[:8],
                "text": text,
                "remind_at": remind_dt.isoformat(),
                "created_at": datetime.now().isoformat(),
                "done": False,
            }
            reminders.append(reminder)
            _save_reminders(reminders)
            return (
                f"Reminder set: '{text}'\n"
                f"Due: {remind_dt.strftime('%A, %B %d %Y at %I:%M %p')}\n"
                f"ID: {reminder['id']}"
            )
        except Exception as e:
            return f"Error adding reminder: {str(e)}"

    @mcp.tool()
    def list_reminders(include_done: bool = False) -> str:
        """
        Show all upcoming (and optionally completed) reminders.
        Use this when the user asks 'what are my reminders?', 'show upcoming tasks', 'what do I need to do?'.
        """
        try:
            reminders = _load_reminders()
            now = datetime.now()

            if not reminders:
                return "No reminders set yet."

            filtered = [r for r in reminders if include_done or not r.get("done", False)]
            if not filtered:
                return "No active reminders. All done!"

            # Sort by remind_at
            filtered.sort(key=lambda r: r.get("remind_at", ""))

            lines = [f"=== REMINDERS ({len(filtered)} total) ===\n"]
            for r in filtered:
                try:
                    due_dt = datetime.fromisoformat(r["remind_at"])
                    overdue = " *** OVERDUE ***" if due_dt < now and not r.get("done") else ""
                    status = "[DONE]" if r.get("done") else "[TODO]"
                    lines.append(
                        f"{status} [{r['id']}] {r['text']}\n"
                        f"        Due: {due_dt.strftime('%a %b %d %Y %I:%M %p')}{overdue}"
                    )
                except Exception:
                    lines.append(f"[?] {r.get('text', '???')}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error listing reminders: {str(e)}"

    @mcp.tool()
    def mark_reminder_done(reminder_id: str) -> str:
        """
        Mark a reminder as completed.
        reminder_id: The ID shown in list_reminders (e.g. 'abc12345').
        Use this when the user says 'mark reminder X as done', 'I completed X', 'dismiss reminder'.
        """
        try:
            reminders = _load_reminders()
            for r in reminders:
                if r.get("id") == reminder_id:
                    r["done"] = True
                    r["completed_at"] = datetime.now().isoformat()
                    _save_reminders(reminders)
                    return f"Reminder '{r['text']}' marked as done."
            return f"No reminder found with ID: {reminder_id}"
        except Exception as e:
            return f"Error marking reminder done: {str(e)}"

    @mcp.tool()
    def delete_reminder(reminder_id: str) -> str:
        """
        Delete a reminder permanently.
        reminder_id: The ID shown in list_reminders.
        Use this when the user says 'delete reminder X', 'remove reminder X'.
        """
        try:
            reminders = _load_reminders()
            original_count = len(reminders)
            reminders = [r for r in reminders if r.get("id") != reminder_id]
            if len(reminders) == original_count:
                return f"No reminder found with ID: {reminder_id}"
            _save_reminders(reminders)
            return f"Reminder {reminder_id} deleted."
        except Exception as e:
            return f"Error deleting reminder: {str(e)}"
