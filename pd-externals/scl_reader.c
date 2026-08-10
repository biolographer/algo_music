#include "m_pd.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

static t_class *scl_reader_class;

typedef struct _scl_reader {
    t_object x_obj;
    t_outlet *out_list;
} t_scl_reader;

/* Method that runs when the object receives a "read" message with a file path */
void scl_reader_read(t_scl_reader *x, t_symbol *s) {
    FILE *file = fopen(s->s_name, "r");
    if (!file) {
        pd_error(x, "scl_reader: could not open file. Try using an absolute path.");
        return;
    }

    char line[256];
    int state = 0;
    int expected_notes = 0;
    int notes_read = 0;
    
    t_atom output_list[256]; /* Limiting to 256 notes for this example */
    int list_index = 0;

    while (fgets(line, sizeof(line), file)) {
        char *ptr = line;
        
        /* Skip whitespace */
        while (*ptr == ' ' || *ptr == '\t') ptr++;
        
        /* Skip comments and empty lines */
        if (*ptr == '!' || *ptr == '\n' || *ptr == '\r' || *ptr == '\0') continue;

        if (state == 0) {
            state = 1; /* Skipped description */
        } else if (state == 1) {
            expected_notes = atoi(ptr);
            state = 2;
        } else if (state == 2) {
            double cents = 0.0;
            
            if (strchr(ptr, '.')) {
                sscanf(ptr, "%lf", &cents);
            } else if (strchr(ptr, '/')) {
                double num, den;
                if (sscanf(ptr, "%lf/%lf", &num, &den) == 2 && den != 0) {
                    cents = 1200.0 * log2(num / den);
                }
            } else {
                double num;
                if (sscanf(ptr, "%lf", &num) == 1) {
                    cents = 1200.0 * log2(num);
                }
            }
            
            /* Store the calculated cents in the Pd list array */
            SETFLOAT(&output_list[list_index], (t_float)cents);
            list_index++;
            notes_read++;
            
            if (notes_read >= expected_notes || list_index >= 256) break;
        }
    }
    fclose(file);
    
    /* Output the final list of cents out the left outlet */
    outlet_list(x->out_list, &s_list, list_index, output_list);
}

void *scl_reader_new(void) {
    t_scl_reader *x = (t_scl_reader *)pd_new(scl_reader_class);
    x->out_list = outlet_new(&x->x_obj, &s_list); /* Create one outlet */
    return (void *)x;
}

void scl_reader_setup(void) {
    scl_reader_class = class_new(gensym("scl_reader"),
        (t_newmethod)scl_reader_new,
        0, sizeof(t_scl_reader), CLASS_DEFAULT, 0);
        
    /* Bind the "read" message to our read function */
    class_addmethod(scl_reader_class, (t_method)scl_reader_read, gensym("read"), A_SYMBOL, 0);
}