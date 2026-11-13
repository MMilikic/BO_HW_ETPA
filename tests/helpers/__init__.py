"""The helpers the tests share, in modules named for what they hold.

Plain functions, classes and constants, imported by name from their module:
`from helpers.participants import A, B`. There are no pytest fixtures, so
everything a test uses is written in the test or one click away.

No helper counts ids: a counter kept in a module would outlive the test that used it.

A module imports only what the tests that use it already need. One that imports
only the interface layer works in every lecture's package. One that imports a
component serves only the tests that need that component, so if the component has
not arrived yet, or a student's file cannot be imported yet, only those tests fail.
"""
