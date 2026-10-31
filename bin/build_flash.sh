#!/usr/bin/env bash

./bin/build.sh $1 && ./bin/flash.sh $1 "$2"
