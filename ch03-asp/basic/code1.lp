% Facts
place(gangnam; hongdae; yeouido).
congested(gangnam; yeouido).

% Rules
advise(X,"방문을 자제하세요") :- place(X), congested(X).
advise(X,"방문해도 좋습니다") :- place(X), not congested(X).

#show advise/2.
