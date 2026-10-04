"""Select the displayed fixture without changing stored match results."""
from datetime import datetime


def select_live_game(games, now):
    dated = []
    for game in games:
        try:
            start = datetime.fromisoformat(game.get("start") or "")
            if start.tzinfo is None:
                continue
        except (ValueError, TypeError):
            continue
        dated.append((game, start.astimezone(now.tzinfo)))

    today = [(game, start) for game, start in dated if start.date() == now.date()]
    if today:
        game, start = min(today, key=lambda item: abs((item[1] - now).total_seconds()))
        confirmed = (
            start <= now
            and bool(game.get("live_source"))
            and game.get("zalgiris_score") is not None
            and game.get("opponent_score") is not None
            and (game.get("live_source") != "LKL.lt" or bool(game.get("lkl_game_id")))
        )
        if confirmed:
            return game

        # A display placeholder is not an official score and must not enter
        # persistent storage or make the coordinator stop fetching live data.
        display = dict(game)
        for key in list(display):
            if key.startswith(("live_", "break_")) or key == "clock_source":
                display[key] = None
        home = str(game.get("home") or "").lower()
        display.update(
            score_home=0, score_away=0, zalgiris_score=0, opponent_score=0,
            opponent=game.get("away") if "žalgiris" in home or "zalgiris" in home else game.get("home"),
            is_live=False, score_pending=True,
            live_status="scheduled" if now < start else "waiting",
            live_state="scheduled" if now < start else "waiting",
        )
        return display

    previous = [(game, start) for game, start in dated if game.get("live_source")]
    if not previous:
        return None
    return min(previous, key=lambda item: abs((item[1] - now).total_seconds()))[0]
