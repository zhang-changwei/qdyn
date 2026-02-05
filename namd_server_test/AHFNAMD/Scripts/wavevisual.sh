#!/bin/bash

prefix=sya

python ../../readwavecar.py
step=$(basename "$PWD")
mv 936wfc_r.vasp "${prefix}_${step}_936wfc_r.vasp"
mv 936wfc_i.vasp "${prefix}_${step}_936wfc_i.vasp"
mv 937wfc_r.vasp "${prefix}_${step}_937wfc_r.vasp"
mv 937wfc_i.vasp "${prefix}_${step}_937wfc_i.vasp"
