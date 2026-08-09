from krabville.db import dumps, initialize, loads
from krabville.world import _weather, advance_tick, start_season


def test_weather_cycles_through_four_seasons_deterministically() -> None:
    seed = "ab" * 32
    first = [_weather(seed, 0, number) for number in range(1, 21)]
    assert [weather["season"] for weather in first] == (
        ["spring"] * 5 + ["summer"] * 5 + ["fall"] * 5 + ["winter"] * 5
    )
    assert first == [_weather(seed, 0, number) for number in range(1, 21)]
    assert first[19]["temperatureC"] < first[9]["temperatureC"]
    assert _weather(seed, 0, 21)["season"] == "winter"


def test_active_legacy_weather_is_repaired_for_the_season_chapter(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="cd" * 32)
    connection.execute(
        "UPDATE seasons SET weather_json=? WHERE number=1",
        (dumps({"season": "summer", "condition": "heatwave", "temperatureC": 35}),),
    )
    connection.commit()

    advance_tick(connection)

    weather = loads(connection.execute("SELECT weather_json FROM seasons WHERE number=1").fetchone()[0], {})
    assert weather == _weather("cd" * 32, 0, 1)
    assert weather["season"] == "spring"
    connection.close()
