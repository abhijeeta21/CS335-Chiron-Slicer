:side = 15
:inc = 6
:n = 24
:parity = 0
repeat :n [
    :parity = :parity + 1
    if (:parity > 1) [
        color "blue"
        :parity = 0
    ]
    else [
        color "red"
    ]
    forward :side
    right 91
    :side = :side + :inc
]