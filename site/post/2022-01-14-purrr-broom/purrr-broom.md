URL: https://youzhi.netlify.app/post/2022-01-14-purrr-broom/purrr-broom/
Title: A Short Introduction on How to Use Purrr in Conjunction with Broom
Date: 2022-01-14
---

In this blog post, I will carry out a basic usage of the package `purrr` in conjunction with the package `broom`. This blog post was motivated by the README file ([link](https://purrr.tidyverse.org/)) of `purrr`. Let's load the packages first and then I will flesh it out.

```r
library(purrr)
library(broom)
library(dplyr)
library(tidyr)
```

Here I copy the code from the link mentioned above.

```r
mtcars %>%
 split(.$cyl) %>% # from base R
 map(~ lm(mpg ~ wt, data = .)) %>%
 map(summary) %>%
 map_dbl("r.squared")
```

```
## 4 6 8
## 0.5086326 0.4645102 0.4229655
```

`mtcars` is a famous data set in the R community. When evaluating the code, there are few things we can change. First off, it uses the `split()` function that is from base R, so is `summary()`. I think this is a great opportunity to illustrate how to combine `purrr::map()` with the broom package to reach the same result as the code output above.

### I. Instead of using `split()`, we use `nest()` from tidyr: {#i.-instead-of-using-split-we-use-nest-from-tidyr}

```r
mtcars %>%
 nest(-cyl)
```

```
## # A tibble: 3 x 2
## cyl data
## <dbl> <list>
## 1 6 <tibble [7 x 10]>
## 2 4 <tibble [11 x 10]>
## 3 8 <tibble [14 x 10]>
```

### II. Using `map()` and `glance()` on the data column: {#ii.-using-map-and-glance-on-the-data-column}

```r
mtcars %>%
 nest(-cyl) %>%
 mutate(model = map(data, ~lm(mpg ~ wt, data = .)),
 glanced = map(model, glance))
```

```
## # A tibble: 3 x 4
## cyl data model glanced
## <dbl> <list> <list> <list>
## 1 6 <tibble [7 x 10]> <lm> <tibble [1 x 12]>
## 2 4 <tibble [11 x 10]> <lm> <tibble [1 x 12]>
## 3 8 <tibble [14 x 10]> <lm> <tibble [1 x 12]>
```

There is another way to do it:

```r
mtcars %>%
 nest(-cyl) %>%
 mutate(model = map(data, ~lm(.$mpg ~ .$wt)),
 glanced = map(model, glance))
```

```
## # A tibble: 3 x 4
## cyl data model glanced
## <dbl> <list> <list> <list>
## 1 6 <tibble [7 x 10]> <lm> <tibble [1 x 12]>
## 2 4 <tibble [11 x 10]> <lm> <tibble [1 x 12]>
## 3 8 <tibble [14 x 10]> <lm> <tibble [1 x 12]>
```

The dot `.` is a pronoun, referring to `data` in this case.

### III. `unnest()` the `tidied`, then `pivot_wider()` {#iii.-unnest-the-tidied-then-pivot_wider}

```r
mtcars %>%
 nest(-cyl) %>%
 mutate(model = map(data, ~lm(mpg ~ wt, data = .)),
 glanced = map(model, glance)) %>%
 unnest(glanced) %>%
 select(cyl, r.squared) %>%
 pivot_wider(names_from = "cyl", values_from = "r.squared")
```

```
## # A tibble: 1 x 3
## `6` `4` `8`
## <dbl> <dbl> <dbl>
## 1 0.465 0.509 0.423
```

Here we have the same output as what the `purrr` README provides. I need to say that both packages are fantastic ones, and they have made my data science life much easier, especially `purrr`. But truth be told, it is not easy to learn `purrr` at the begining. If you want to learn more about both packages, I would recommend check out their documentation and Github repos.
