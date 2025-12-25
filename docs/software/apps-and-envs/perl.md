# Perl

Perl is available as a software module. No additional perl modules have been
installed. Installing local modules using local::lib with cpanm is the
preferred method. Here is an example to install and test Math::CDF:

```default
module load perl
eval $(perl -I$HOME/perl5/lib/perl5 -Mlocal::lib)
cpanm Math::CDF
perl -e "require Math::CDF"
```

To have the appropriate environment available during login, it is recommended
to put these lines in the $HOME/.bashrc:

```default
module load perl
[ $SHLVL -eq 1 ] && eval "$(perl -I$HOME/perl5/lib/perl5 -Mlocal::lib)"
```

Additional details on local::lib can be in the [local::lib documentation](http://search.cpan.org/perldoc/local::lib).
