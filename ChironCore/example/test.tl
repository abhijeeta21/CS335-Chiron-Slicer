:side = 80
color "red"
repeat 4 [
    forward :side
    right 90
]
penup
goto (200, 0)
pendown
color "blue"
repeat 3 [
    forward :side
    right 120
]
penup
goto (0, 200)
pendown
color "green"
repeat 6 [
    forward :side
    right 60
]