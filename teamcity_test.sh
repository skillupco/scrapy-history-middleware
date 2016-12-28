#!/bin/bash

wrapper=
for file in "/usr/share/virtualenvwrapper/virtualenvwrapper.sh" "/usr/local/bin/virtualenvwrapper.sh"
do
    echo -n "Does \`${file}' exists ? "
    [ -f "${file}" ] && { wrapper="$file" ; echo "yes" ; } || { echo "no" ; }
    [ -n "${wrapper}" ] && break
done
[ -z "${wrapper}" ] && { echo "Please install virtualenvwrapper" 1>&2 ; exit 1 ; }

export WORKON_HOME="/home/teamcity/.virtualenvs"
source "${wrapper}"
workon teamcity 2> /dev/null
if [ "0" != "$?" ]
then
    echo "Please setup a virtualenv named \`teamcity' for this test-runner."
    exit 1
fi

pip install --upgrade -r requirements.txt

/bin/bash runtests.sh
