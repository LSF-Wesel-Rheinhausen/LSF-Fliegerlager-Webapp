# Fix manual settlement run creation with subsidies

Manual settlement runs no longer return HTTP 500 when a participant has a
subsidized charge. The cost-center snapshot now serializes both persisted
expenses and calculated subsidy details.
