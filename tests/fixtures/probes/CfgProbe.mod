MODULE CfgProbe
    ! robconv - arm configuration probe. Run PROC Probe (no motion):
    ! it writes the confdata computed for each joint set to HOME:/cfgprobe.txt
    !  1: reference
    !  2: J5 positive
    !  3: J5 small neg
    !  4: J5 small pos
    !  5: J4 +185
    !  6: J4 -185
    !  7: J6 +190
    !  8: J6 -190
    !  9: J6 +350
    ! 10: J2 +40 J3 +60
    ! 11: J2 +40 J3 -60
    ! 12: J2 -60 J3 -80
    ! 13: J2 -60 J3 +80
    ! 14: J2 +60 J3 +80
    ! 15: J1 +90
    ! 16: J1 -150
    CONST jointtarget JT{16}:=[
        [[0,0,0,0,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,0,0,0,90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,0,0,0,-30,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,0,0,0,30,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,0,0,185,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,0,0,-185,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,0,0,0,-90,190],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,0,0,0,-90,-190],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,0,0,0,-90,350],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,40,60,0,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,40,-60,0,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,-60,-80,0,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,-60,80,0,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[0,60,80,0,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[90,0,0,0,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]],
        [[-150,0,0,0,-90,0],[9E9,9E9,9E9,9E9,9E9,9E9]]];

    PROC Probe()
        VAR iodev f;
        VAR robtarget p;
        Open "HOME:" \File:="cfgprobe.txt", f \Write;
        FOR i FROM 1 TO Dim(JT,1) DO
            p:=CalcRobT(JT{i},tool0\WObj:=wobj0);
            Write f, NumToStr(i,0)+" "+ValToStr(p.robconf)+" "+ValToStr(JT{i}.robax);
        ENDFOR
        Close f;
        TPWrite "cfgprobe.txt written in HOME:";
    ENDPROC
ENDMODULE
