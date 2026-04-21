:seed = 25
:unrelated = 30

:a = :seed * 5
forward :a

left :unrelated
forward 100

:b = 100
right :unrelated
backward :b