URL: https://youzhi.netlify.app/post/2021-08-09-summarize-vs-summarize/summarize-vs-summarise/
Title: Summarize Vs Summarise
---

# dplyr::summarize() V.S. dplyr::summarise()

#### Y. Yu

#### 2021-08-09

## Background Introduction {#background-introduction}

As an avid R user for years, I’ve been using `tidyverse` ecosystem to do my data science work daily and from time to time would come across something new from the tools I use all the time. Last night, as I was building up one of my shiny apps/dashboards by adding test of association of tweets collected from different sampling methods, I found out one of the differences between `dplyr::summarize()` and `dplyr::summarise()`.

In order to get correlations and p-values, I used a function `rcorr()` from `library(Hmisc)`. When I added this function into my shiny app, it did not work as it should and my dashboard gave me some strange error message. To better illustrate my points, using `mtcars` dataset would shed some light on what I would like to convey.

First off, let’s load the respective packages.

```r
library(dplyr)
library(Hmisc)
```

The following code to me has nothing wrong, as this is the way I usually code, but it has thrown me a strange error. Truth be told, I was confused for a while and did a number of unit testings and checked `Hmisc` documentation on how the function `rcorr()` should work, but nothing really stood out and the same strange error appeared over and over.

```r
mtcars %>% group_by(gear, carb) %>%
 summarize(mean(mpg), mean(disp), mean(hp), mean(drat), mean(wt)) %>%
 as.matrix() %>%
 rcorr()
```

```
## Error in mean(disp): object 'disp' not found
```

After searching on stackoverflow and github, I found out this [link](https://github.com/tidyverse/dplyr/issues/505), which amazed me in a way that I found out a difference between `dplyr::summarize` and `dplyr::summarise`. To me, they were just the American and British spelling and the code would be doing the same job no matter which one we use, but after I changed `z` to `s` for the snippet code, I ended up having the following correct results. Pretty amazing, right?

```r
mtcars %>% group_by(gear, carb) %>%
 summarise(mean(mpg), mean(disp), mean(hp), mean(drat), mean(wt)) %>%
 as.matrix() %>%
 rcorr()
```

```
## gear carb mean(mpg) mean(disp) mean(hp) mean(drat) mean(wt)
## gear 1.00 0.52 0.25 -0.33 0.27 0.72 -0.53
## carb 0.52 1.00 -0.57 0.33 0.81 -0.04 0.36
## mean(mpg) 0.25 -0.57 1.00 -0.90 -0.79 0.59 -0.92
## mean(disp) -0.33 0.33 -0.90 1.00 0.75 -0.54 0.88
## mean(hp) 0.27 0.81 -0.79 0.75 1.00 -0.24 0.61
## mean(drat) 0.72 -0.04 0.59 -0.54 -0.24 1.00 -0.69
## mean(wt) -0.53 0.36 -0.92 0.88 0.61 -0.69 1.00
##
## n= 11
##
##
## P
## gear carb mean(mpg) mean(disp) mean(hp) mean(drat) mean(wt)
## gear 0.1025 0.4500 0.3262 0.4195 0.0132 0.0938
## carb 0.1025 0.0681 0.3217 0.0025 0.8957 0.2720
## mean(mpg) 0.4500 0.0681 0.0002 0.0036 0.0551 0.0000
## mean(disp) 0.3262 0.3217 0.0002 0.0082 0.0843 0.0004
## mean(hp) 0.4195 0.0025 0.0036 0.0082 0.4866 0.0462
## mean(drat) 0.0132 0.8957 0.0551 0.0843 0.4866 0.0183
## mean(wt) 0.0938 0.2720 0.0000 0.0004 0.0462 0.0183
```

## Conclusion {#conclusion}

I guess besides spelling difference, there is some underlying structural variations between `summarise()` and `summarize()`. Part of the reason why I like data science and do research work in this field enthusiastically is that I always encounter strange errors, some of which are not solved even after checking all components associated with them, but seeing questions and answers posted by people in this collegial community would always give me the right guidance to solving the problems I encounter at any moment. Through conferring and researching the technical questions/problems, I can consistently sharpen my data science tools.
