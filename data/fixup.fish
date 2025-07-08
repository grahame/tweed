#!/usr/bin/env fish

for i in cookbooks.txt crime.txt first-nations.txt liturgy.txt poetry-and-epic-myth.txt romance.txt speculative-fiction.txt;
        echo $i
        cat "$i" | sort | uniq > "$i".n && mv "$i".n "$i"
end
