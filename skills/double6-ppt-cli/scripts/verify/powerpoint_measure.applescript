-- Measure template-fill outputs in Microsoft PowerPoint for Mac (best effort; read-only on inputs).
on run argv
	set inPosix to item 1 of argv
	set outDir to item 2 of argv
	set baseName to item 3 of argv
	set report to ""
	tell application "Microsoft PowerPoint"
		if (count of presentations) is not 0 then error "unsafe_preexisting_presentations"
		open (POSIX file inPosix as alias)
		repeat 240 times
			if (count of presentations) > 0 then exit repeat
			delay 0.25
		end repeat
		set deck to active presentation
		set n to count of slides of deck
		repeat with si from 1 to n
			set sl to slide si of deck
			repeat with shi from 1 to count of shapes of sl
				set sh to shape shi of sl
				try
					set report to report & "F" & tab & si & tab & (name of sh) & tab & (left position of sh) & tab & (top of sh) & tab & (width of sh) & tab & (height of sh) & linefeed
				end try
				try
					if has text frame of sh then
						set tf to text frame of sh
						set bh to "?"
						set au to "?"
						set fs to "?"
						try
							set bh to (bound height of text range of tf) as text
						end try
						try
							set au to (auto size of text frame 2 of sh) as text
						end try
						try
							set fs to (font size of font of text range of tf) as text
						end try
						set report to report & si & tab & (name of sh) & tab & (height of sh) & tab & bh & tab & au & tab & fs & tab & (margin top of tf) & tab & (margin bottom of tf) & tab & (left position of sh) & tab & (top of sh) & tab & (width of sh) & linefeed
					end if
				end try
			end repeat
		end repeat
		save deck in (POSIX file (outDir & "/" & baseName & ".powerpoint.pdf")) as save as PDF
		save deck in (POSIX file (outDir & "/" & baseName & ".powerpoint.pptx")) as save as Open XML presentation
		close deck saving no
	end tell
	return report
end run
