#!/bin/sh
# An IDE keeps its SDKs in its own settings, and a development container cannot set
# one up yet. Run as root while the image is built, before IntelliJ first starts. The
# folders are writable by anyone, so the IDE can use them whatever UID the user ends up
# with once the container is made.
#
# Each version of IntelliJ reads its own folder, named for it, and the version a
# container gets is not known until IntelliJ starts it, after this build. So the SDK
# goes into the folder of every version the course may meet, by the same naming: 2026.1,
# the first to run a local feature, to 2027.3. 2026.2 was checked with it. A folder no
# version reads is never looked at.
set -e
jetbrains_settings=/.jbdevcontainer/config/JetBrains
mkdir -p "$jetbrains_settings"
chmod 777 /.jbdevcontainer /.jbdevcontainer/config "$jetbrains_settings"
for version in 2026.1 2026.2 2026.3 2027.1 2027.2 2027.3; do
    intellij_settings="$jetbrains_settings/IntelliJIdea$version"
    mkdir -p "$intellij_settings/options"
    cp "$(dirname "$0")/jdk.table.xml" "$intellij_settings/options/"
    chmod -R a+rwX "$intellij_settings"
done
