#!/bin/bash

# Test dacrawl using nose.
#    --with-doctest              => located and run doctests
#    --with-cov                  => calculate test coverage
#    --cov-report=html           => generate html report for test coverage
#    --cover-erase               => remove old coverage statistics
#    --cov-config                => use coverage config file

# This script will pass any arguments to the end of the nosetests
# invocation. For example:
#    (venv)$ ./runtests.sh --pdb-failure # will drop into pdb on failure

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

nosetests \
    --with-doctest \
    --with-cov --cov-report=html --cov-config .coveragerc --cover-erase \
    $@
