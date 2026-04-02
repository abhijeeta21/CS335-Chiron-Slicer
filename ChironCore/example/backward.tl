:step = 10
:acc = 0
repeat 2 [
    :acc = :acc + :step
]
:target = :acc + 5
forward :target
:x = 3
:y = 5
:z = :x + :y