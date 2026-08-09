from krabville.world import _weather


def test_weather_cycles_through_four_seasons_deterministically() -> None:
    seed = "ab" * 32
    first = [_weather(seed, 0, number) for number in range(1, 5)]
    assert [weather["season"] for weather in first] == ["spring", "summer", "fall", "winter"]
    assert first == [_weather(seed, 0, number) for number in range(1, 5)]
    assert first[3]["temperatureC"] < first[1]["temperatureC"]
    assert _weather(seed, 0, 5)["season"] == "spring"
