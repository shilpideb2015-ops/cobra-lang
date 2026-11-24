================================================================================
COBRA v2.0 - FULL USAGE & DISTRIBUTION GUIDE (WINDOWS STANDALONE)
================================================================================

1. OVERVIEW
Cobra v2.0 provides a standalone Windows runtime (cobra.exe) and compiler
(cobrac.exe) that execute Cobra (.cobra) scripts and compiled bytecode
(.cobrabc) files without requiring Python or PyInstaller on the end user's PC.

Typical release files:
- cobra.exe         : Runs .cobra source scripts and .cobrabc bytecode files
- cobrac.exe        : Compiles .cobra source scripts into .cobrabc bytecode
- cobra.ico         : Application icon
- examples\         : Sample .cobra scripts (such as main.cobra)
- README.txt        : This instruction file


2. RUNNING A .COBRA SCRIPT DIRECTLY
Open Command Prompt (cmd) in the Cobra v2.0 folder (or use full paths):

  cobra.exe examples\main.cobra


3. COMPILING TO BYTECODE (.cobrabc) AND RUNNING
Compile a source script into bytecode, then run the bytecode file:

  cobrac.exe my_program.cobra my_program.cobrabc
  cobra.exe my_program.cobrabc

Compile and run in one command (if supported by your cobrac build):

  cobrac.exe my_program.cobra --run


4. CREATING A DOUBLE-CLICK LAUNCHER (.bat)
To launch a program easily without typing runtime commands each time, place a
.bat file in the same folder as your .cobrabc file:

  @echo off
  cobra.exe "%~dp0my_program.cobrabc" %*

Double-clicking my_program.bat runs the compiled program using cobra.exe in
the script's directory (or from PATH).


5. MAKING A STANDALONE .EXE FILE (FOR BUILDERS / DEVELOPERS)
End users who only extract the release package run .cobra or .cobrabc files
through cobra.exe / cobrac.exe (or via a .bat launcher or prebuilt stub .exe).

If you are building a standalone Windows .exe on a machine with Python and
PyInstaller installed:
1) Wrap your .cobra script inside a Python launcher script that invokes
   cobra.exe (or your Cobra runtime execution entry point).
2) Build a single-file executable with PyInstaller:

     python -m PyInstaller --onefile --clean --icon=cobra.ico --name my_app launcher.py


6. COBRA v2 SYNTAX BASICS
Example snippet showing @use directives, 1-based list indexing (.num(1)),
function definitions (func name.is.(...)), type helpers (int, sentence), and
output statements:

  @use code
  @use math
  @use language
  @use list

  # 1-based indexing starts at .num(1)
  students = list.sentence("Aarav", "Riya", "Kabir")
  first_student = students.num(1)

  func make_greeting.is.(person_name, bonus_points)
  {
      total = 10 + bonus_points
      from language; math print("Hello " sentence(person_name) "! Score: " int(total)).nextln
      return(total)
  }

  final_pts = make_greeting.is.int(first_student, 15)
  from language; math print("Final points: " int(final_pts)).nextln


7. VERIFYING RELEASE ARCHIVES (SHA-256)
Before extracting Cobra-2.0.0-win64-portable.zip, verify its SHA-256 hash
against Cobra-2.0.0-win64-portable.zip.sha256 in Command Prompt:

  certutil -hashfile Cobra-2.0.0-win64-portable.zip SHA256

Compare the output hash with the value inside Cobra-2.0.0-win64-portable.zip.sha256.
================================================================================
