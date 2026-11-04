"""Wire-assertion smoke with fixture policy, not production Rego qualification.

Calling the scenario directly avoids starting OPA locally. Hosted CI still runs
its original test with the real production-policy fixture and mandatory binary.
"""

import pytest
from test_project_history_real_policy import (
    test_production_policy_allows_authorized_project_routing_recording_and_recall as policy_scenario,
)


@pytest.mark.asyncio
async def test_policy_scenario_wire_assertions_with_fixture_authority(
    tmp_path, authority_parts
):
    await policy_scenario(tmp_path, authority_parts)
