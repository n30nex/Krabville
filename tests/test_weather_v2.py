from krabville.world import _weather


def test_weather_cycles_through_four_seasons_deterministically() -> None:
    seed = "ab" * 32
    first = [_weather(seed, 0, number) for number in range(1, 21)]
    assert [weather["season"] for weather in first] == (
        ["spring"] * 5 + ["summer"] * 5 + ["fall"] * 5 + ["winter"] * 5
    )
    assert first == [_weather(seed, 0, number) for number in range(1, 21)]
    assert first[19]["temperatureC"] < first[9]["temperatureC"]
    assert _weather(seed, 0, 21)["season"] == "winter"
