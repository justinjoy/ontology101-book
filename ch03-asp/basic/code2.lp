% --- Facts ---
person(alice; bob; charlie).
attends(alice, concert).
attends(bob,   concert).
late(bob).

% --- Rule ---
enjoys(X) :- attends(X, concert), not late(X).

#show enjoys/1.
