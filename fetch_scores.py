data = api_get(
    "fixtures",
    {
        "league": 1,
        "season": 2026
    },
    api_key
)

print("Fixtures found:", len(data["response"]))