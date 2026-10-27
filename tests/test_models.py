from sitescribe import MediaType, Observation, PlanLocation


def test_observation_with_location():
    obs = Observation(
        media_type=MediaType.TEXT,
        text="Spalling at column base",
        location=PlanLocation(plan_id="S-201", x=0.42, y=0.17, label="Grid C-4"),
    )
    assert obs.location.plan_id == "S-201"
    assert len(obs.id) == 8
