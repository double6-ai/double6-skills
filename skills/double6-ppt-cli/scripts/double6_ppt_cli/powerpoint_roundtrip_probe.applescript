on run argv
    set inputPosix to item 1 of argv
    set outputPosix to item 2 of argv
    set inputAlias to (POSIX file inputPosix) as alias
    set slideNumber to (item 3 of argv) as integer
    set textShapeName to item 4 of argv
    set replacementText to item 5 of argv
    set moveShapeName to item 6 of argv
    set moveDelta to (item 7 of argv) as real
    set performEdit to (item 8 of argv) is "true"
    set pdfOutputPosix to item 9 of argv
    set outputHfs to (POSIX file outputPosix) as text
    set outputDir to do shell script "/usr/bin/dirname " & quoted form of outputPosix
    set outputName to do shell script "/usr/bin/basename " & quoted form of outputPosix
    set appWasRunning to application "Microsoft PowerPoint" is running
    set initialPresentationCount to 0
    set pageCount to 0
    set saveAsFlag to false
    set editSaveFlag to false
    set titlePersisted to false
    set movePersisted to false
    set fontEmbeddingWarning to false
    set originalLeft to 0.0
    set requestedLeft to 0.0
    set observedLeft to 0.0
    set currentStage to "preflight"

    try
        with timeout of 600 seconds
            tell application "Microsoft PowerPoint"
                set currentStage to "count_presentations"
                set initialPresentationCount to count of presentations
                if initialPresentationCount is not 0 then error "unsafe_preexisting_presentations:" & initialPresentationCount
                set currentStage to "activate"
                activate
                set currentStage to "open_input"
                open inputAlias
                repeat 480 times
                    if (count of presentations) > 0 then exit repeat
                    delay 0.25
                end repeat
                if (count of presentations) is 0 then error "presentation_did_not_open"
                set deck to active presentation
                set pageCount to count of slides of deck
                set currentStage to "export_pdf"
                save deck in POSIX file pdfOutputPosix as save as PDF
                do shell script "/bin/test -s " & quoted form of pdfOutputPosix
                set currentStage to "move_window_to_secondary_display"
                tell application "System Events"
                    tell process "Microsoft PowerPoint"
                        set position of window 1 to {-2200, 210}
                        set size of window 1 to {1900, 1000}
                    end tell
                end tell
                set currentStage to "open_save_as_dialog"
                tell application "System Events"
                    tell process "Microsoft PowerPoint"
                        click menu item "另存为..." of menu "文件" of menu bar 1
                        delay 1
                        keystroke "g" using {command down, shift down}
                        delay 1
                        set value of text field 1 of sheet 1 of sheet 1 of window 1 to outputDir
                        key code 36
                        delay 1
                        set value of text field "保存为：" of splitter group 1 of sheet 1 of window 1 to outputName
                        click button "保存" of splitter group 1 of sheet 1 of window 1
                    end tell
                end tell
                set currentStage to "wait_for_save_as"
                repeat 480 times
                    tell application "System Events"
                        tell process "Microsoft PowerPoint"
                            try
                                set dialogName to name of window 1 as text
                                if dialogName contains "连同字体保存" or dialogName contains "Save with Fonts" then
                                    set fontEmbeddingWarning to true
                                    key code 36
                                end if
                            end try
                        end tell
                    end tell
                    try
                        do shell script "/bin/test -s " & quoted form of outputPosix
                        exit repeat
                    on error
                        delay 0.25
                    end try
                end repeat
                do shell script "/bin/test -s " & quoted form of outputPosix
                set currentStage to "read_save_as_flag"
                set saveAsFlag to saved of deck
                set currentStage to "close_after_save_as"
                close deck saving no

                set currentStage to "resolve_output_alias_1"
                set outputAlias to my aliasForPath(outputPosix)
                set currentStage to "reopen_save_as_output"
                open outputAlias
                repeat 480 times
                    if (count of presentations) > 0 then exit repeat
                    delay 0.25
                end repeat
                if (count of presentations) is 0 then error "save_as_output_did_not_reopen"
                set deck to active presentation

                if performEdit then
                    set currentStage to "edit_text"
                    set titleShape to shape textShapeName of slide slideNumber of deck
                    set content of text range of text frame of titleShape to replacementText
                    set currentStage to "move_shape"
                    set moveShape to shape moveShapeName of slide slideNumber of deck
                    set originalLeft to left position of moveShape
                    set requestedLeft to originalLeft + moveDelta
                    set left position of moveShape to requestedLeft
                    set currentStage to "save_edit"
                    save deck
                    repeat 80 times
                        tell application "System Events"
                            tell process "Microsoft PowerPoint"
                                try
                                    set dialogName to name of window 1 as text
                                    if dialogName contains "连同字体保存" or dialogName contains "Save with Fonts" then
                                        set fontEmbeddingWarning to true
                                        key code 36
                                        exit repeat
                                    end if
                                end try
                            end tell
                        end tell
                        delay 0.25
                    end repeat
                    set currentStage to "read_edit_save_flag"
                    set editSaveFlag to saved of deck
                end if
                set currentStage to "close_after_edit"
                close deck saving no

                set currentStage to "resolve_output_alias_2"
                set outputAlias to my aliasForPath(outputPosix)
                set currentStage to "reopen_edited_output"
                open outputAlias
                repeat 480 times
                    if (count of presentations) > 0 then exit repeat
                    delay 0.25
                end repeat
                if (count of presentations) is 0 then error "edited_output_did_not_reopen"
                set deck to active presentation
                if performEdit then
                    set currentStage to "verify_text"
                    set titleShape to shape textShapeName of slide slideNumber of deck
                    set observedText to content of text range of text frame of titleShape
                    set titlePersisted to observedText is replacementText
                    set currentStage to "verify_move"
                    set moveShape to shape moveShapeName of slide slideNumber of deck
                    set observedLeft to left position of moveShape
                    set movePersisted to (observedLeft > requestedLeft - 0.2) and (observedLeft < requestedLeft + 0.2)
                else
                    set titlePersisted to true
                    set movePersisted to true
                    set editSaveFlag to true
                end if
                set currentStage to "final_close"
                close deck saving no
                if not appWasRunning then quit
            end tell
        end timeout
        return "status=passed;initial_count=" & initialPresentationCount & ";slides=" & pageCount & ";pdf_exported=true;save_as_saved=" & saveAsFlag & ";edit_saved=" & editSaveFlag & ";title_persisted=" & titlePersisted & ";move_persisted=" & movePersisted & ";font_embedding_warning=" & fontEmbeddingWarning & ";left=" & originalLeft & "->" & observedLeft
    on error errorText number errorNumber
        try
            tell application "Microsoft PowerPoint"
                if initialPresentationCount is 0 then
                    repeat while (count of presentations) > 0
                        close active presentation saving no
                    end repeat
                end if
                if not appWasRunning then quit
            end tell
        end try
        return "status=failed;stage=" & currentStage & ";error_number=" & errorNumber & ";error=" & errorText
    end try
end run

on aliasForPath(posixPath)
    return (POSIX file posixPath) as alias
end aliasForPath
