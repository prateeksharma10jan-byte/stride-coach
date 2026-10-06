"""Per-user brain: events -> facts (pure Python) -> guarded LLM interpretation -> Telegram."""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path

from app import charts, guard
from app.metrics import endurance as endu
from app.metrics import muscles, plan as planner
from app.metrics import strength as stre
from app.metrics import trends
from app.parsers.hevy import parse_description

log = logging.getLogger("stride.bot")
PROMPTS = Path(__file__).parent / "prompts"
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
STRENGTH_TYPES = {"WeightTraining"}
SESSION_WINDOW_S = 30 * 60
HELP = ("/last - re-open your latest workout\n/week - last 7 days + muscle sets\n"
        "/pr - best lifts\n/plan [2-5] - next week's run plan\n"
        "/chart [zones|pace|volume|e1rm|weekly]\n/dashboard - web dashboard link\n"
        "/goal <text> - set your goal\n/hr <max> [rest] - set your heart rates\n"
        "/export - download your data\n/forget - wipe workouts & chat\n"
        "/deleteaccount - delete everything incl. Strava link")


def _prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def llm_view(facts: dict) -> dict:
    """What the LLM sees: everything except bulky chart series."""
    return {k: v for k, v in facts.items() if k != "series"}


def fallback_summary(f: dict) -> str:
    """Deterministic message used when the LLM is capped, down, or fails the guard."""
    if f["kind"] == "run":
        return (f"**{f['name']}** - {f['distance_km']} km in {f['duration_min']} min "
                f"({f['avg_pace_per_km']}/km, avg HR {f['avg_hr']}). "
                f"Load ratio: {f['acwr_label']}.")
    s = f"**{f['name']}** - {f['total_sets']} sets, {f['total_volume_kg']:g} kg total volume."
    for p in f.get("prs", []):
        s += f"\nPR: {p['exercise']} e1RM {p['new_e1rm_kg']} kg (+{p['improvement_kg']})."
    return s


class Bot:
    def __init__(self, settings, udb, strava, telegram, llm, user: dict,
                 dashboard_url=None, clock=time.time):
        self.s, self.db, self.strava, self.tg, self.llm = settings, udb, strava, telegram, llm
        self.user, self.chat_id, self.now = user, user["telegram_chat_id"], clock
        self.dashboard_url = dashboard_url or (lambda: "")

    # ============================================================ strava
    def handle_strava_event(self, ev: dict) -> bool:
        """create -> analyse. update -> only if we're missing data (e.g. Hevy synced late)."""
        if ev.get("object_type") != "activity":
            return False
        aid, aspect = int(ev["object_id"]), ev.get("aspect_type")
        if aspect == "create":
            self.process_activity(aid)
            return True
        if aspect == "update":
            known = self.db.get_activity(aid)
            if known is None or (known["kind"] != "run" and self.db.set_count(aid) == 0):
                self.process_activity(aid)
                return True
        return False

    def process_activity(self, activity_id: int, quiet_if_empty: bool = False) -> None:
        try:
            act = self.strava.get_activity(activity_id)
            sport = act.get("sport_type") or act.get("type")
            if sport in RUN_TYPES:
                facts, load = self._run_facts(act)
            elif sport in STRENGTH_TYPES:
                facts, load = self._strength_facts(act)
                if facts is None:
                    if not self.db.get_activity(activity_id):  # don't nag on repeated updates
                        self._say(f"Got **{act.get('name')}** but couldn't find sets in the "
                                  "description yet. If Hevy syncs late I'll pick it up on update.")
                        self.db.save_activity(activity_id, act["start_date"], "strength_pending",
                                              act.get("name", ""), 0.0, {"kind": "pending"})
                    return
            else:
                return
            self.db.save_activity(activity_id, act["start_date"], facts["kind"],
                                  facts["name"], load, facts)
            if facts["kind"] == "run":
                day = datetime.fromisoformat(act["start_date"].replace("Z", "+00:00")).date()
                val = endu.acwr(self.db.daily_loads(60), day)  # includes this run's load
                facts["acwr"], facts["acwr_label"] = val, endu.acwr_label(val)
                facts["vs_recent"] = trends.compare_to_recent(
                    facts, self.db.run_history(exclude_id=activity_id))
            text = self._analyse(facts)
            self.db.save_activity(activity_id, act["start_date"], facts["kind"],
                                  facts["name"], load, facts, text)
            self._say(text)
            for name in charts.choose_charts(facts):
                png, cap = charts.render(name, facts, self.db)
                self.tg.send_photo(self.chat_id, png, cap)
            self.db.set_session(activity_id, [{"role": "assistant", "content": text}], self.now())
        except Exception:
            log.exception("process_activity failed for %s", activity_id)
            raise  # let the job queue retry with backoff

    def _run_facts(self, act):
        sid = act["id"]
        st = self.strava.get_streams(sid)
        t, hr, v = st.get("time", []), st.get("heartrate", []), st.get("velocity_smooth", [])
        past_peaks = [h.get("max_hr_seen", 0) for h in self.db.run_history(exclude_id=sid)]
        max_hr = endu.effective_max_hr(self.user["max_hr"], past_peaks)
        rest_hr = self.user["rest_hr"]
        secs = endu.hr_zone_seconds(t, hr, max_hr) if hr else [0.0] * 5
        zp = endu.zone_percentages(secs)
        avg_hr = act.get("average_heartrate") or 0
        dur = act.get("moving_time", 0)
        load = endu.trimp(dur, avg_hr, rest_hr, max_hr) if avg_hr else 0.0
        laps = [{"n": i, "distance_km": round(lap["distance"] / 1000, 2),
                 "pace_per_km": endu.pace_str(lap.get("average_speed", 0)),
                 "avg_hr": round(lap.get("average_heartrate") or 0)}
                for i, lap in enumerate(self.strava.get_laps(sid)[:30], 1)]
        series = {"t": [round(x / 60, 2) for x in endu.downsample(t)],
                  "hr": endu.downsample(hr) if hr else [],
                  "pace": [min(1000 / x, 900) if x > 0.5 else 900
                           for x in endu.downsample(v)] if v else []}
        if not (series["hr"] and series["pace"]):
            series = {"t": [], "hr": [], "pace": []}
        speed = act["distance"] / dur if dur else 0
        facts = {
            "kind": "run", "activity_id": sid, "name": act.get("name", "Run"),
            "date": act["start_date"][:10],
            "distance_km": round(act.get("distance", 0) / 1000, 2),
            "duration_min": round(dur / 60, 1),
            "avg_speed_ms": round(speed, 3), "avg_pace_per_km": endu.pace_str(speed),
            "avg_hr": round(avg_hr), "max_hr_seen": max(hr) if hr else 0,
            "max_hr_used_for_zones": max_hr,
            "zone_pct": {f"Z{i + 1}": p for i, p in enumerate(zp)},
            "decoupling_pct": endu.decoupling_pct(t, hr, v) if hr and v else None,
            "trimp": load, "laps": laps, "series": series, "acwr": None,
            "acwr_label": "not enough history", "vs_recent": None,
        }
        return facts, load

    def _strength_facts(self, act):
        title, sets = parse_description(act.get("description"))
        if not sets:
            return None, 0.0
        summary = stre.summarize(sets)
        prior = self.db.best_e1rms(exclude_activity_id=act["id"])
        prs = stre.detect_prs(summary["exercises"], prior)
        day = act["start_date"][:10]
        self.db.replace_sets(act["id"], day, [(s.exercise, s.weight_kg, s.reps,
                                               stre.e1rm(s.weight_kg, s.reps)) for s in sets])
        plateaus = [e["name"] for e in summary["exercises"]
                    if stre.lift_plateau(self.db.e1rm_history(e["name"]))]
        facts = {"kind": "strength", "activity_id": act["id"],
                 "name": title or act.get("name", "Workout"), "date": day,
                 "prs": prs, "plateaued_lifts": plateaus, **summary}
        return facts, 0.0

    # ============================================================ llm (guarded)
    def _llm_allowed(self) -> bool:
        return self.db.incr_llm_calls(date.today().isoformat()) <= self.s.llm_daily_cap

    def _goal(self) -> str:
        return self.db.get_kv("goal") or ""

    def _guarded(self, system: str, messages: list[dict], facts: dict, max_tokens: int):
        """Call the LLM; if it states a number not in FACTS, retry once, else return None."""
        out = self.llm.complete(system, messages, max_tokens=max_tokens)
        bad = guard.ungrounded_numbers(out, llm_view(facts), self._goal())
        if not bad:
            return out
        log.warning("guard rejected LLM output; ungrounded numbers: %s", bad)
        if not self._llm_allowed():
            return None
        retry = messages + [
            {"role": "assistant", "content": out},
            {"role": "user", "content": f"Your reply contained numbers that are not in FACTS: "
                                        f"{bad}. Rewrite using ONLY numbers from FACTS."}]
        out2 = self.llm.complete(system, retry, max_tokens=max_tokens)
        return None if guard.ungrounded_numbers(out2, llm_view(facts), self._goal()) else out2

    def _analyse(self, facts: dict) -> str:
        if not self._llm_allowed():
            return fallback_summary(facts)
        goal = f"\nGOAL: {self._goal()}" if self._goal() else ""
        try:
            out = self._guarded(_prompt("analyst"), [{"role": "user", "content":
                                f"FACTS:\n{json.dumps(llm_view(facts))}{goal}"}], facts, 700)
        except Exception:
            log.exception("LLM analysis failed")
            out = None
        return out or fallback_summary(facts)

    # ============================================================ telegram
    def _say(self, text: str) -> None:
        self.tg.send_markdown(self.chat_id, text)

    def handle_message(self, text: str) -> None:
        text = text.strip()
        if text.startswith("/"):
            self._command(text)
        else:
            self._chat(text)

    def _command(self, text: str) -> None:
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.split("@")[0].lower(), arg.strip()
        handler = {
            "/start": lambda: self._say(HELP), "/help": lambda: self._say(HELP),
            "/last": self._cmd_last, "/week": self._cmd_week, "/pr": self._cmd_pr,
            "/plan": lambda: self._cmd_plan(arg), "/chart": lambda: self._chart_cmd(arg),
            "/goal": lambda: self._cmd_goal(arg), "/hr": lambda: self._cmd_hr(arg),
            "/dashboard": self._cmd_dashboard, "/export": self._cmd_export,
            "/forget": self._cmd_forget,
            "/deleteaccount": lambda: self._cmd_delete(arg),
        }.get(cmd)
        (handler or (lambda: self._say("Unknown command.\n" + HELP)))()

    def _cmd_last(self):
        a = self.db.last_activity()
        if not a or a["kind"] == "strength_pending":
            return self._say("No analysed workouts yet.")
        self.db.set_session(a["id"], [{"role": "assistant", "content": a["analysis"]}], self.now())
        self._say((a["analysis"] or fallback_summary(a["facts"]))
                  + "\n\nAsk me anything about it (30 min).")

    def _cmd_week(self):
        acts = [a for a in self.db.recent_activities(7) if a["kind"] != "strength_pending"]
        if not acts:
            return self._say("Nothing in the last 7 days.")
        runs = [a for a in acts if a["kind"] == "run"]
        lifts = [a for a in acts if a["kind"] == "strength"]
        km = sum(a["facts"]["distance_km"] for a in runs)
        vol = sum(a["facts"]["total_volume_kg"] for a in lifts)
        msg = (f"**Last 7 days**\nRuns: {len(runs)} ({km:.1f} km)\n"
               f"Lifts: {len(lifts)} ({vol:,.0f} kg volume)")
        ms = muscles.weekly_sets(self.db.recent_sets(7))
        if ms:
            msg += "\n\n**Sets per muscle group**\n" + "\n".join(f"- {m}: {n}" for m, n in ms.items())
        self._say(msg)

    def _cmd_pr(self):
        best = self.db.best_e1rms()
        if not best:
            return self._say("No lifting data yet.")
        rows = sorted(best.items(), key=lambda kv: -kv[1])[:10]
        self._say("**Best estimated 1RMs**\n" + "\n".join(f"- {k}: {v:g} kg" for k, v in rows))

    def weekly_run_km(self, weeks: int = 4) -> list[float]:
        out = [0.0] * weeks
        today = date.today()
        for a in self.db.recent_activities(7 * weeks):
            if a["kind"] == "run":
                d = date.fromisoformat(a["start_date"][:10])
                i = (today - d).days // 7
                if 0 <= i < weeks:
                    out[i] += a["facts"]["distance_km"]
        return out

    def _cmd_plan(self, arg: str):
        n = int(arg) if arg.isdigit() else 4
        acwr = endu.acwr(self.db.daily_loads(60), date.today())
        p = planner.weekly_plan(acwr, self.weekly_run_km(), n)
        if not p:
            return self._say("I need at least some recent running (and 2-5 runs/week) to plan.")
        rows = "\n".join(f"- {s['day']}: {s['type']} - {s['km']:g} km" for s in p["sessions"])
        self._say(f"**Next week: ~{p['target_km']:g} km** (recent avg {p['baseline_km']:g} km)\n"
                  f"{p['reason'].capitalize()}.\n\n{rows}")

    def _chart_cmd(self, arg: str):
        if arg not in charts.REGISTRY:
            return self._say("Charts: " + ", ".join(charts.REGISTRY))
        a = self.db.last_activity()
        if not a and arg != "weekly":
            return self._say("No workouts stored yet.")
        try:
            png, cap = charts.render(arg, a["facts"] if a else {}, self.db)
        except (KeyError, IndexError):
            return self._say("That chart doesn't apply to your latest workout type.")
        self.tg.send_photo(self.chat_id, png, cap)

    def _cmd_goal(self, arg: str):
        if arg:
            self.db.set_kv("goal", arg[:300])
            self._say("Goal saved.")
        else:
            self._say(f"Current goal: {self._goal() or 'none'}")

    def _cmd_hr(self, arg: str):
        parts = arg.split()
        if not parts or not all(p.isdigit() for p in parts) or len(parts) > 2:
            return self._say(f"Usage: /hr <max> [rest]. Now: max {self.user['max_hr']}, "
                             f"rest {self.user['rest_hr']}.")
        mx = int(parts[0])
        rs = int(parts[1]) if len(parts) == 2 else self.user["rest_hr"]
        if not (140 <= mx <= 230 and 30 <= rs <= 100 and rs < mx):
            return self._say("Those values look off (max 140-230, rest 30-100).")
        self.db.db.set_hr(self.db.uid, mx, rs)
        self.user = dict(self.user, max_hr=mx, rest_hr=rs)
        self._say(f"Saved: max HR {mx}, resting HR {rs}.")

    def _cmd_dashboard(self):
        url = self.dashboard_url()
        self._say(f"Your dashboard (link valid 24h):\n{url}" if url else "Dashboard unavailable.")

    def _cmd_export(self):
        data = json.dumps(self.db.export_all(), indent=2).encode()
        self.tg.send_document(self.chat_id, "stride-export.json", data, "Your data")

    def _cmd_forget(self):
        self.db.wipe_data()
        self._say("All stored workouts, sets, settings and chat history deleted.")

    def _cmd_delete(self, arg: str):
        if arg != "confirm":
            return self._say("This permanently deletes everything and unlinks Strava.\n"
                             "Send `/deleteaccount confirm` to proceed.")
        self._say("Account deleted. Send /start any time to set up again.")
        self.db.delete_account()

    def _chat(self, text: str):
        sess = self.db.get_session()
        if not sess or self.now() - sess["last_ts"] > SESSION_WINDOW_S:
            return self._say("No active chat. Use /last to reopen your latest workout.")
        act = self.db.get_activity(sess["activity_id"])
        if not act or not self._llm_allowed():
            return self._say("Daily AI limit reached - try again tomorrow.")
        history = sess["history"] + [{"role": "user", "content": text}]
        goal = f"\nGOAL: {self._goal()}" if self._goal() else ""
        system = _prompt("chat") + f"\nFACTS:\n{json.dumps(llm_view(act['facts']))}{goal}"
        try:
            reply = self._guarded(system, history[-12:], act["facts"], 400)
        except Exception:
            log.exception("LLM chat failed")
            return self._say("Couldn't reach the AI just now - try again in a moment.")
        if reply is None:
            return self._say("I can't answer that reliably from your recorded data.")
        history.append({"role": "assistant", "content": reply})
        self.db.set_session(sess["activity_id"], history[-12:], self.now())  # slides the window
        self._say(reply)
